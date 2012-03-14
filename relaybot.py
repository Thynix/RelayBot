from twisted.words.protocols import irc
from twisted.internet import reactor, protocol
from twisted.internet.protocol import ReconnectingClientFactory
from twisted.python import log
from twisted.internet.endpoints import clientFromString
from twisted.application import service
from signal import signal, SIGINT
from ConfigParser import SafeConfigParser
import re, sys

#
# RelayBot is a derivative of http://code.google.com/p/relaybot/
#

log.startLogging(sys.stdout)

__version__ = "0.1"
application = service.Application("RelayBot")

def main():
    config = SafeConfigParser()
    config.read("relaybot.config")
    defaults = config.defaults()
    
    for section in config.sections():
        
        def get(option):
            return config.get(section, option) or defaults[option]
        
        options = {}
        for option in [ "timeout", "host", "port", "nick", "channel", "info", "heartbeat" ]:
            options[option] = get(option)
        
        mode = get("mode")
        
        #Not using endpoints pending http://twistedmatrix.com/trac/ticket/4735
        #(ReconnectingClientFactory equivalent for endpoints.)
        factory = None
        if mode == "Default":
            factory = RelayFactory
        elif mode == "FLIP":
            factory = FLIPFactory
        elif mode == "NickServ":
            factory = NickServFactory
            options["nickServPassword"] = get("nickServPassword")
        
        factory = factory(options)
        reactor.connectTCP(options['host'], int(options['port']), factory, int(options['timeout']))
    
    reactor.callWhenRunning(signal, SIGINT, handler)

class Communicator:
    def __init__(self):
        self.protocolInstances = {}

    def register(self, protocol):
        self.protocolInstances[protocol.identifier] = protocol

    def isRegistered(self, protocol):
        return protocol.identifier in self.protocolInstances

    def unregister(self, protocol):
        if protocol.identifier not in self.protocolInstances:
            log.msg("No protocol instance with identifier %s."%protocol.identifier)
            return
        del self.protocolInstances[protocol.identifier]

    def relay(self, protocol, message):
        for identifier in self.protocolInstances.keys():
            if identifier == protocol.identifier:
                continue
            instance = self.protocolInstances[identifier]
            instance.twoWaySay(message)

#Global scope: all protocol instances will need this.
communicator = Communicator()

class IRCRelayer(irc.IRCClient):
    realname = "Relay P. Botternson"
    username = "RelayBot"
    
    def __init__(self, config):
        self.network = config['host']
        self.channel = config['channel']
        self.nickname = config['nick']
        self.identifier = config['identifier']
        self.privMsgResponse = config['info']
        self.heartbeatInterval = float(config['heartbeat'])
        log.msg("IRC Relay created. Name: %s | Host: %s | Channel: %s"%(self.nickname, self.network, self.channel))

    def formatUsername(self, username):
        return username.split("!")[0]

    def relay(self, message):
        communicator.relay(self, message)

    def signedOn(self):
        log.msg("[%s] Connected to network."%self.network)
        self.startHeartbeat()
        self.join(self.channel, "")
    
    def connectionLost(self, reason):
        log.msg("[%s] Connection lost, unregistering."%self.network)
        communicator.unregister(self)
    
    def twoWaySay(self, message, args=None):
        self.say(self.channel, message)
    
    def joined(self, channel):
        log.msg("Joined channel %s, registering."%channel)
        communicator.register(self)
    
    def privmsg(self, user, channel, message):
        #If someone addresses the bot directly, respond in the same way.
        if channel == self.nickname:
            log.msg("Recieved privmsg from %s."%user)
            self.msg(user, self.privMsgResponse)
        else:
            self.relay("[%s] %s"%(self.formatUsername(user), message))
            if message.startswith(self.nickname + ':'):
                self.say(self.channel, self.privMsgResponse)
                #For consistancy, if anyone responds to the bot's response:
                self.relay("[%s] %s"%(self.formatUsername(self.nickname), self.privMsgResponse))
    
    def kickedFrom(self, channel, kicker, message):
        log.msg("Kicked by %s. Message \"%s\""%(kicker, message))
        communicator.unregister(self)
    
    def userJoined(self, user, channel):
        self.relay("%s joined."%self.formatUsername(user))
    
    def userLeft(self, user, channel):
        self.relay("%s left."%self.formatUsername(user))
    
    def userQuit(self, user, quitMessage):
        self.relay("%s quit. (%s)"%(self.formatUsername(user), quitMessage))
    
    def action(self, user, channel, data):
        self.relay("* %s %s"%(self.formatUsername(user), data))
    
    def userRenamed(self, oldname, newname):
        self.relay("%s is now known as %s."%(self.formatUsername(oldname), self.formatUsername(newname)))
    
     
class RelayFactory(ReconnectingClientFactory):
    protocol = IRCRelayer
    #Log information which includes reconnection status.
    noisy = True
    
    def __init__(self, config):
        config["identifier"] = "{0}{1}{2}".format(config["host"], config["port"], config["channel"])
        self.config = config
    
    def buildProtocol(self, addr):
        #Connected - reset reconnect attempt delay.
        self.resetDelay()
        x = self.protocol(self.config)
        x.factory = self
        return x

#Remove the _<numbers> that FLIP puts on the end of usernames.
class FLIPRelayer(IRCRelayer):
    def formatUsername(self, username):
        return re.sub("_\d+$", "", IRCRelayer.formatUsername(self, username))

class FLIPFactory(RelayFactory):
    protocol = FLIPRelayer

#Identify with NickServ upon connecting, and wait for recognition before joining the channel.
class NickServRelayer(IRCRelayer):
    NickServ = "nickserv"

    def signedOn(self):
        log.msg("[%s] Connected to network."%self.network)
        self.startHeartbeat()
        if self.nickname == self.desiredNick:
            log.msg("[%s] Identifying with %s."%(self.network, NickServRelayer.NickServ))
            self.msg(NickServRelayer.NickServ, "IDENTIFY %s"%self.password)
        else:
            log.msg("[%s] Using GHOST to reclaim nick %s."%(self.network, self.desiredNick))
            self.msg(NickServRelayer.NickServ, "GHOST %s %s"%(self.desiredNick, self.password))
    
    def noticed(self, user, channel, message):
        if IRCRelayer.formatUsername(self, user) == NickServRelayer.NickServ\
                    and (message == "Password accepted -- you are now recognized." or message == "Ghost with your nickname has been killed."):
            if communicator.isRegistered(self):
                log.msg("[%s] Recieved duplicate password acception from %s."%(self.network, NickServRelayer.NickServ))
                return
            log.msg("[%s] Identified with %s; joining %s."%(self.network, NickServRelayer.NickServ, self.channel))
            if self.nickname != self.desiredNick:
                log.msg("[%s] GHOST successful, reclaiming nick."%self.network)
                self.setNick(self.desiredNick)
            self.join(self.channel, "")
        else:
            log.msg("[%s] Recieved notice \"%s\" from %s."%(self.network, message, user))
    
    def __init__(self, config):
        IRCRelayer.__init__(self, config)
        #super(NickServRelayer, self).__init__(config)
        self.password = config['nickServPassword']
        self.haveDesiredNick = True
        self.desiredNick = self.nickname

class NickServFactory(RelayFactory):
    protocol = NickServRelayer

def handler(signum, frame):
	reactor.stop()

#Main if run as script, builtin for twistd.
if __name__ in ["__main__", "__builtin__"]:
        main()

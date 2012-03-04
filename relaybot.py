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
        timeout = config.get(section, "timeout") or defaults["timeout"]
        host = config.get(section, "host") or defaults["host"]
        port = config.get(section, "port") or defaults["port"]
        nick = config.get(section, "nick") or defaults["nick"]
        channel = config.get(section, "channel") or defaults["channel"]
        privReply = config.get(section, "info") or defaults["info"]
        kind = config.get(section, "mode") or defaults["mode"]
        
        #Not using endpoints pending http://twistedmatrix.com/trac/ticket/4735
        #(ReconnectingClientFactory equivalent for endpoints.)
        factory = None
        if kind == "FLIP":
            factory = FLIPFactory
        else:
            factory = RelayFactory
        
        factory = factory(host, channel, port, nick, privReply)
        reactor.connectTCP(host, int(port), factory, int(timeout))
    
    reactor.callWhenRunning(signal, SIGINT, handler)

class Communicator:
    def __init__(self):
        self.protocolInstances = {}

    def register(self, protocol):
        self.protocolInstances[protocol.identifier] = protocol

    def unregister(self, protocol):
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
    
    def __init__(self, name, network, channel, identifier, privMsgResponse):
        self.network = network
        self.channel = channel
        self.nickname = name
        self.identifier = identifier
        self.privMsgResponse = privMsgResponse
        log.msg("IRC Relay created. Name: %s | Host: %s | Channel: %s"%(name, network, channel))

    def formatUsername(self, username):
        return username.split("!")[0]

    def relay(self, message):
        communicator.relay(self, message)

    def signedOn(self):
        log.msg("[%s] Connected to network."%self.network)
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
        user.relay("%s quit. (%s)"%(self.formatUsername(user), quitMessage))
    
    def action(self, user, channel, data):
        self.relay("* %s %s"%(self.formatUsername(user), data))
    
    def userRenamed(self, oldname, newname):
        self.relay("%s is now known as %s."%(self.formatUsername(oldname), self.formatUsername(newname)))
    
     
class RelayFactory(ReconnectingClientFactory):
    protocol = IRCRelayer
    #Log information which includes reconnection status.
    noisy = True
    
    def __init__(self, network, channel, port, name, privMsgResponse):
        self.network = network
        self.channel = channel
        self.name = name
        self.port = port
        self.privMsgResponse = privMsgResponse
    
    def buildProtocol(self, addr):
        #Connected - reset reconnect attempt delay.
        self.resetDelay()
        identifier = (self.network, self.channel, self.port)
        x = self.protocol(self.name, self.network, self.channel, identifier, self.privMsgResponse)
        x.factory = self
        return x

#Remove the _<numbers> that FLIP puts on the end of usernames.
class FLIPRelayer(IRCRelayer):
    def formatUsername(self, username):
        return re.sub("_\d+$", "", IRCRelayer.formatUsername(self, username))

class FLIPFactory(RelayFactory):
    protocol = FLIPRelayer

def handler(signum, frame):
	reactor.stop()

#Main if run as script, builtin for twistd.
if __name__ in ["__main__", "__builtin__"]:
        main()

from twisted.words.protocols import irc
from twisted.internet import reactor, protocol
from twisted.internet.protocol import ReconnectingClientFactory
from twisted.python import log
from twisted.internet.endpoints import clientFromString
from signal import signal, SIGINT
import re

import sys

log.startLogging(sys.stdout)

__version__ = "0.2"

def main():
    host = "localhost"
    timeout = 120
    
    preamble = "This is a bot which relays traffic between #i2p-bridge on FLIP and #flip-bridge on I2Prc. "
    
    contactFreenet = "Freemail: operhiem1@oblda5d6jfleur3uomyws52uljrvo4l2jbuwcwsuk54tcn3qi5ehqwlsojvdaytcjnseslbnki3fozckj5ztaqkblb3gw3dwmreeg6dhk5te2ncyj55hgmkmkq4xoytworgdkrdpgvvsyqkrifbucqkf.freemail"
    
    contactI2P = "I2P-bote: operhiem1@QcTYSRYota-9WDSgfoUfaOkeSiPc7cyBuHqbgJ28YmilVk66-n1U1Zf1sCwTS2eDxlk4iwMZuufRmATsPJdkipw4EuRfaHLXKktwtkSTXNhciDsTMgJn7Ka14ayVuuPiF2tKzyaCTV4H2vc7sUkOKLsH9lyccVnFdYOnL~bkZiCGDI"
    
    #Configure channels here:
    #Tuple order is (hostname or IP, port, response when privmsg'd or referred to in chat, special behavior)
    for host, port, channel, privReply, kind in [(host, 6667, "#i2p-bridge", preamble+contactFreenet, "FLIP"),\
                                                 (host, 6669, "#test-lol", preamble+contactI2P, None)]:
        
        #Not using endpoints pending http://twistedmatrix.com/trac/ticket/4735
        #(ReconnectingClientFactory equivalent for endpoints.)
        factory = None
        if kind == "FLIP":
            factory = FLIPFactory(host, channel, privReply, port)
        else:
            factory = RelayFactory(host, channel, privReply, port)
        
        reactor.connectTCP(host, port, factory)
    
    reactor.callWhenRunning(signal, SIGINT, handler)
    reactor.run()

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
        return username

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
        user = user.split("!")[0]
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
    
    def __init__(self, network, channel, privMsgResponse = "I am a bot", port=6667, name = "RelayBot"):
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
        return re.sub("_\d+$", "", username)

class FLIPFactory(RelayFactory):
    protocol = FLIPRelayer

def handler(signum, frame):
	reactor.stop()

if __name__ == "__main__":
        main()

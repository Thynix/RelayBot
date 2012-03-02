from twisted.words.protocols import irc
from twisted.internet import reactor, protocol
from twisted.python import log
from twisted.internet.endpoints import clientFromString
from signal import signal, SIGINT

import sys

log.startLogging(sys.stdout)

__version__ = "0.2"

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
                log.msg("Not relaying to self")
                continue
            instance = self.protocolInstances[identifier]
            log.msg(identifier, instance)
            instance.twoWaySay(message)

#Global scope: all protocol instances will need this.
communicator = Communicator()

class IRCRelayer(irc.IRCClient):
    realname = "Relay P. Botternson"
    username = "RelayBot"
    
    def __init__(self, name, network, channel, identifier):
        self.network = network
        self.channel = channel
        self.nickname = name
        self.identifier = identifier
        self.privMsgResponse = "This is a relay bot between I2P #flip-bridge and FLIP #i2p-bridge. operhiem1 <Freemail: operhiem1@oblda5d6jfleur3uomyws52uljrvo4l2jbuwcwsuk54tcn3qi5ehqwlsojvdaytcjnseslbnki3fozckj5ztaqkblb3gw3dwmreeg6dhk5te2ncyj55hgmkmkq4xoytworgdkrdpgvvsyqkrifbucqkf.freemail I2P-bote: operhiem1@QcTYSRYota-9WDSgfoUfaOkeSiPc7cyBuHqbgJ28YmilVk66-n1U1Zf1sCwTS2eDxlk4iwMZuufRmATsPJdkipw4EuRfaHLXKktwtkSTXNhciDsTMgJn7Ka14ayVuuPiF2tKzyaCTV4H2vc7sUkOKLsH9lyccVnFdYOnL~bkZiCGDI>"
        log.msg("IRC Relay created. Name: %s | Network: %s "%(name, network))

    def relay(self, message):
        communicator.relay(self, message)

    def signedOn(self):
        log.msg("[%s] Connected to network"%self.network)
        self.join(self.channel, "")
    
    def connectionLost(self, reason):
        log.msg("[%s] Connection lost, unregistering"%self.network)
        communicator.unregister(self)
    
    def twoWaySay(self, message, args=None):
        log.msg("[TwoWay] Saying %s into channel %s"%(message, self.channel))
        self.say(self.channel, message)
    
    def joined(self, channel):
        log.msg("I joined channel %s, registering"%channel)
        communicator.register(self)
    
    def privmsg(self, user, channel, message):
        user = user.split("!")[0]
        log.msg("Got message \"%s\""%message)
        self.relay(message)
        if message.startswith(self.nickname + ':'):
            log.msg("%s sent me privmsg."%user)
            self.msg(user, self.privMsgResponse)
    
    def kickedFrom(self, channel, kicker, message):
        log.msg("Kicked by %s. Message \"%s\""%(kicker, message))
        communicator.unregister(self)
    
    def nickChanged(self, nick):
        log.msg("My nick is now %s"%nick)
    
    def userJoined(self, user, channel):
        self.relay("%s joined"%user)
    
    def userLeft(self, user, channel):
        self.relay("%s left"%user)
    
    def userQuit(self, user, quitMessage):
        user.relay("User %s quit (%s)"%(user, quitMessage))
    
    def action(self, user, channel, data):
        self.relay("* %s %s"%(user, data))
    
    def userRenamed(self, oldname, newname):
        self.relay("User %s changed nick to %s"%(oldname, newname))
    
     
class BaseFactory(protocol.ClientFactory):
    noisy = False
    def clientConnectionLost(self,connector,reason):
        if hasattr(self, "terminated"):
            if self.terminated:
                connector.disconnect()
                return log.msg("ClientFactory %s closing down"%self)
        log.msg('Disconnect. Reason: %s'%reason.getErrorMessage())
        reactor.callLater(5, connector.connect)

    def clientConnectionFailed(self,connector,reason):
        if hasattr(self, "terminated"):
            if self.terminated:
                connector.disconnect()
                return log.msg("ClientFactory %s closing down"%self)
        log.msg('Disconnect. Reason: %s'%reason.getErrorMessage())
        reactor.callLater(5, connector.connect)

class RelayFactory(BaseFactory):
    protocol = IRCRelayer
    
    def __init__(self, network, channel, port=6667, name = "RelayBot"):
        self.network = network
        self.channel = channel
        self.name = name
        self.port = port
        self.terminated = False
    
    def buildProtocol(self, addr):
        identifier = (self.network, self.channel, self.port)
        x = self.protocol(self.name, self.network, self.channel, identifier)
        x.factory = self
        return x
    
    def clientConnectionLost(self, connector, reason):
        """If we get disconnected, reconnect to server."""
        #TODO: reconnecting factory thing
        connector.connect()

def handler(signum, frame):
	reactor.stop()

hostname = "localhost"
timeout = 120

def clientString(hostname, port):
    return "tcp:host={0}:port={1}".format(hostname, port)

botOneF = RelayFactory(hostname, "#i2p-bridge", 6667)
connectionOne = clientFromString(reactor, clientString(hostname, 6667))
botOneDeferred = connectionOne.connect(botOneF)

botTwoF = RelayFactory(hostname, "#test-lol", 6669)
connectionTwo = clientFromString(reactor, clientString(hostname, 6669))
botTwoDeferred = connectionTwo.connect(botTwoF)

reactor.callWhenRunning(signal, SIGINT, handler)
reactor.run()

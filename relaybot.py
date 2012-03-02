from twisted.words.protocols import irc
from twisted.internet import reactor, protocol
from twisted.python import log
from twisted.application import internet, service

# To Do::
# Make the RelayBots only connect after HomeRelayBot has connected

import ConfigParser
import sys

log.startLogging(sys.stdout)

__version__ = "0.2"

class IRCRelayer(irc.IRCClient):
    ''' This class joins an external network/channel and then
        pumps all messages back through the manager to the
        right relay bot '''
    
    realname = "rbo"
    username = "rbo"
    
    def __init__(self, manager, name, network, channels):
        self.manager = manager
        self.network = network
        self.channels = channels
        self.nickname = name
        log.msg("IRC Relay created. Name: %s | Network: %s | Manager: %s"%(name, network, manager))

    def __call__(
    
    def signedOn(self):
        log.msg("[%s Connected to network, registering"%self.network)
        self.manager.RegisterTwoWay(self.network, self.twoWayComs)
        self.manager.RegisterTwoWay(self.network, self.joinAChannel, type="join")
        self.manager.RegisterTwoWay(self.network, self.leaveAChannel, type="leave")
        for chan, passw in self.channels:
            print("Joining ", chan)
            self.join(chan, passw)
    
    def joinAChannel(self, channel, message, args=None):
        log.msg("[%s] Joining channel %s - %s"%(self.network, channel, message))
        self.manager.CallRelay(self.network, channel, "Joining channel %s"%channel)
        self.join(channel, message)
    
    def leaveAChannel(self, channel, message, args=None): # message is the reason
        log.msg("[%s] Leaving channel %s: %s"%(self.network, channel, message))
        self.leave(channel, message)
        self.manager.CallRelay(self.network, None, "Left channel %s with reason %s"%(channel, message))
    
    def connectionLost(self, reason):
        log.msg("[%s] Connection lost, unregistering"%self.network)
        self.manager.CallRelay(self.network, None, "Lost connection to %s: %s"%(self.network, reason))
        self.manager.UnregisterTwoWay(self.network)
    
    def twoWayComs(self, channel, message, args):
        log.msg("[TwoWay] Saying %s into channel %s"%(message, channel))
        self.say(channel,"[%s] %s"%(args,message))
    
    def joined(self, channel):
        self.manager.CallRelay(self.network, channel, "I joined channel %s"%channel)
    
    def left(self, channel):
        self.manager.CallRelay(self.network, channel, "I left channel %s"%channel)
    
    def privmsg(self, user, channel, message):
        user = user.split("!")[0]
        self.manager.CallRelay(self.network, channel, "%s: %s"%(user, message))
    
    def modeChanged(self, user, channel, set, modes, args):
        if set: set = "+"
        else: set = "-"
        targs = ""
        for x in args:
            if x: targs+=x
        self.manager.CallRelay(self.network, channel, "Mode %s%s %s by %s"%(set, modes,
                                                                            targs, user))
    
    def userKicked(self, kickee, channel, kicker, message):
        self.manager.CallRelay(self.network, channel, "%s kicked %s (%s)"%(kicker, kickee, message))
    
    def kickedFrom(self, channel, kicker, message):
        self.manager.CallRelay(self.network, channel, "%s kicked me! Rude. Message = %s"%(kicker, message))
    
    def nickChanged(self, nick):
        self.manager.CallRelay(self.network, None, "My nick is now %s"%nick)
    
    def userJoined(self, user, channel):
        self.manager.CallRelay(self.network, channel, "%s joined"%user)
    
    def userLeft(self, user, channel):
        self.manager.CallRelay(self.network, channel, "%s left"%user)
    
    def userQuit(self, user, quitMessage):
        self.manager.CallRelay(self.network, None, "User %s quit (%s)"%(user, quitMessage))
    
    def action(self, user, channel, data):
        self.manager.CallRelay(self.network, channel, "%s: %s"%(user, data), type="action")
    
    def topicUpdated(self, user, channel, newTopic):
        self.manager.CallRelay(self.network, channel, "User %s changed the topic to %s"%(user, newTopic))
    
    def userRenamed(self, oldname, newname):
        self.manager.CallRelay(self.network, None, "User %s changed their name to %s"%(oldname, newname))
        
        
class BaseFactory(protocol.ClientFactory):
    noisy = False
    def clientConnectionLost(self,connector,reason):
        if hasattr(self, "terminated"):
            if self.terminated:
                connector.disconnect()
                return log.msg("ClientFactory %s closing down"%self)
        log.msg('Disconnect. Reason: %s'%reason.getErrorMessage())
        reactor.callLater(3, connector.connect)

    def clientConnectionFailed(self,connector,reason):
        if hasattr(self, "terminated"):
            if self.terminated:
                connector.disconnect()
                return log.msg("ClientFactory %s closing down"%self)
        log.msg('Disconnect. Reason: %s'%reason.getErrorMessage())
        reactor.callLater(3, connector.connect)

class RelayFactory(BaseFactory):
    protocol = IRCRelayer
    
    def __init__(self, manager, name, network, channels):
        self.manager = manager
        self.network = network
        self.channels = channels
        self.name = name
        self.terminated = False
    
    def buildProtocol(self, addr):
        x = self.protocol(self.manager, self.name, self.network, self.channels)
        x.factory = self
        return x
    

class RelayManager():
    def __init__(self, config):
        self.config = config
        self.relay = {}
        self.two_way = {} # for inter-network chatz
        
        # (connector, factory)
        self.connectors = {}
        
    def networkExists(self, network):
        return network in self.config.sections()
    
    def enumerateNetworks(self):
        r = []
        for x in self.connectors.keys():
            y = x.split("-")[0]
            if not y in r: r.append(y)
        return r
    
    def enumNetworkKeys(self, network, obj):
        r = []
        for x in obj.keys():
            y = x.split("-")[0]
            if y == network:
                r.append(x)
        return r
        
    def RegisterRelay(self, network, function, type="msg"):
        f = "%s-%s"%(network, type)
        assert not f in self.relay, "Relay %s already registered"%f
        self.relay[f] = function
        log.msg("[Manager] Relay (%s) registered for network %s"%(type,network))

    def CallRelay(self, network, chan, message, type="msg"):
        f = "%s-%s"%(network, type)
        if not f in self.relay: return log.msg("[Manager] Unknown relay %s called"%f)
        self.relay[f](chan, message)
    
    def UnregisterRelay(self, network, type="msg"):
        ''' We dont care if it doesn't exist '''
        for x in self.enumNetworkKeys(network, self.relay):
            del self.relay[x]
            log.msg("[Manager] Relay (%s) removed for network %s"%(x,network))
        return

    def RegisterTwoWay(self, network, function, type="msg"):
        f = "%s-%s"%(network,type)
        assert not f in self.two_way, "Two-Way %s already registered"%f
        self.two_way[f] = function
        log.msg("[Manager] Two-way registered for network %s"%network)
    
    def CallTwoWay(self, network, channel, message, type="msg", args=None):
        f = "%s-%s"%(network, type)
        if not f in self.two_way: return log.msg("[Manager] Unknown two-way (%s) called"%f)
        self.two_way[f](channel, message, args=args)
    
    def UnregisterTwoWay(self, network, type="msg"):
        for x in self.enumNetworkKeys(network, self.two_way):
            del self.two_way[x]
            log.msg("[Manager] Relay (%s) removed for network %s"%(x,network))
    
    def _makeExternalRelay(self, nick, network, port, channels):
        if not network in self.connectors:
            self.connectors[network] = []
        factory = RelayFactory(self, nick, network, channels)
        connector = internet.TCPClient(network, port, factory)
        connector.setServiceParent(application)
        self.connectors[network].append((connector,
                        factory))
        self.RegisterRelay(network, factory)
        
    def _disconnectRelay(self, network):
        for connector, factory in self.connectors[network]:
            factory.terminated = True
            connector.stopService()
        del self.connectors[network]
            
    def TerminateRelay(self, network):
        self._disconnectRelay(network)
    
    def ConnectRelay(self, network):
        port, ident, nickname, channels = self.ReadNetworkSettings(network)
        self.SetupRelay(network, channels, port, nickname, ident)
    
    def SetupRelay(self, external_network, external_channel, external_port, external_nick, home_nick):
        log.msg("Setting up relay for network %s:%s, %s, %s, %s"%(external_network, 
                                                                  external_port, external_channel,
                                                                  external_nick, home_nick))
        self._makeExternalRelay(external_nick or "RelayBot", external_network, 
                                external_port, external_channel)
        
    
    def ReadNetworkSettings(self, network):
        port = config.getint(network, "port")
        ident = config.get(network, "ident")
        nickname = config.get(network, "nickname") or "RelayBot"
        channels = []
        for i in config.options(network):
            if i.startswith("channel_"):
                c = i.split("channel_")[1]
                password = config.get(network,i)
                channels.append((c,password))
        
        return port, ident, nickname, channels

application = service.Application("RelayBot") 

config = ConfigParser.ConfigParser()
config.read("networks.ini")
mangr = RelayManager(config)    

for network in config.sections():
    log.msg("[Config] Creating relay for network %s"%network)
        
    port, ident, nickname, channels = mangr.ReadNetworkSettings(network)
    
    print(port, ident, nickname, channels)        
    
    mangr.SetupRelay(network, channels, port, nickname, ident)

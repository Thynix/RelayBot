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

class IRCClientWithCommands(irc.IRCClient):
    some_command_prefix = ["!"]
    def privmsg(self, user, channel, message):
        if hasattr(self, "channel"):
            c_channel = self.channel
        else:
            if isinstance(self.factory.channel, tuple):
                c_channel = self.factory.channel[0]
            else:
                c_channel = self.factory.channel
        if not channel == c_channel:
            log.msg("Outside msg (%s - %s) from user/chan %s: %s"%(c_channel, channel, user, message))
            return
    
        if not message: return
        if not message.split(" ")[0] == self.nickname: 
            return
        
        command_name = message.split(" ")[1]
        user         = user.split("!")[0]
        args         = message.split(" ")[2:]
        
        if hasattr(self, "need_auth"):
            if self.need_auth:
                if not self.factory.UserIsAuthed(user):
                    return
        
        if hasattr(self, "_gotCustomCommand"):
            return getattr(self,"_gotCustomCommand")(command_name, user, channel, args)
        
        if not hasattr(self,"command_"+command_name):
            return self.msg(channel, "Unknown command %s. use help"%command_name)
        
        getattr(self, "command_"+command_name)(channel, user, args)
    
    def command_help(self, channel, user, args):
        ''' how i use bot??? '''
        self.notice(user,"Commands:")
        for x in dir(self):
            if x.startswith("command_"):
                func = getattr(self, x)
                if not hasattr(func, "__doc__"):
                    ds = "No help available"
                else:
                    ds = func.__doc__
                self.notice(user, "%s - %s"%(
                                             x.split("command_")[1],
                                             ds
                                             ))


class IRCHomeRelayBot(IRCClientWithCommands):
    ''' This class joins the home network and sits in the relay
        channel, spitting out any messages it gets via the manager '''
    
    def __init__(self, manager, name, network, channel):
        self.manager = manager
        self.network = network
        self.chan_auth = channel
        self.channel = self.chan_auth[0]
        self.nickname = name
        
    def signedOn(self):
        log.msg("[home-%s] Connected to network, registering"%self.network)
        self.manager.RegisterRelay(self.network, self.gotRelayMessage)
        self.manager.RegisterRelay(self.network, self.gotActionMessage, type="action")
        self.join(self.chan_auth[0], self.chan_auth[1])
        
    def connectionLost(self, reason):
        log.msg("[home-%s] Connection lost, unregistering"%self.network)
        self.manager.UnregisterRelay(self.network)
    
    def gotRelayMessage(self, channel, message):
        self.say(self.channel, "[%s] %s"%(channel, message))
    
    def gotActionMessage(self, channel, message):
        self.describe(self.channel, "[%s] %s"%(channel, message))
    
    def ctcpQuery(self, user, channel, messages):
        log.msg("[home-%s] [CTCP] Denied from %s"%(self.network, user))
    
    def joined(self, channel):
        self.say(channel, "RelayBot %s"%__version__)
    
    def _gotCustomCommand(self, command, user, channel, args):
        ''' We want users to be able to simply say the following in a channel:
            [nickname] #achan YO YO YO!!11!1
            and the HomeRelayBot will take the message and send it through the two-way.
            So this _gotCustomCommand is a horrible hack to facilitate this.
            '''
        
        if not command.startswith("#"): return
        
        if not args:
            return
        
        message = " ".join(args)
        
        self.manager.CallTwoWay(self.network, command, message, args=(user))
        self.say(channel, "[%s] [%s] %s"%(command, user, message))


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
    
    def signedOn(self):
        log.msg("[%s Connected to network, registering"%self.network)
        self.manager.RegisterTwoWay(self.network, self.twoWayComs)
        self.manager.RegisterTwoWay(self.network, self.joinAChannel, type="join")
        self.manager.RegisterTwoWay(self.network, self.leaveAChannel, type="leave")
        for chan, passw in self.channels:
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
        
class RelayManager(IRCClientWithCommands):
    ''' This bot controls the relay on the fly,
        making connections to new servers and altering the config '''
        
    nickname = "RelayManager"
    need_auth = True
    
    def signedOn(self):
        self.join(self.factory.channel[0], self.factory.channel[1])
    
    def command_add_user(self, channel, user, args):
        ''' add_user [username] - Add a user! '''
        if not args: return self.notice(user, "Invalid args!")
        self.factory.AddUser(args[0])
        return self.notice(user, "Added user %s!"%args[0])
    
    def command_remove_user(self, channel, user, args):
        ''' remove_user [username] - Remove a user! '''
        if not args: return self.notice(user, "Invalid args!")
        if not self.factory.RemoveUser(args[0]):
            return self.notice(user, "Unknown user %s!"%args[0])
        return self.notice(user, "User %s removed from auth list"%args[0])
    
    def command_list_users(self, channel, user, args):
        ''' List users that can use this bot '''
        self.notice(user, "Users:")
        for u in self.factory.EnumerateUsers():
            self.notice(user, " - %s"%u)
        
    def command_kill(self, channel, user, args):
        ''' kill [network] - Kill a relay but leave the config alone'''
        log.msg("Got kill request from user %s in channel %s"%(user, channel))
        if not args: return self.notice(user, "Invalid arguments, use help command")
        network_id = args[0]
        if not self.factory.networkExists(network_id):
            return self.notice(user, "Network %s does not seem to exist! Try the list command"%network_id)
        self.factory.TerminateRelay(network_id)
    
    def command_connect(self, channel, user, args):
        ''' connect [network] - connect a killed relay'''
        if not args: return self.notice(user, "Invalid arguments, use help command")
        network_id = args[0]
        if not self.factory.networkExists(network_id):
            return self.notice(user, "Network %s does not seem to exist! try the view_all command")
        self.factory.ConnectRelay(network_id)
    
    def command_list(self, channel, user, args):
        ''' List all connected networks '''
        self.notice(user, "Connected networks:")
        for c in self.factory.enumerateNetworks():
            self.notice(user, " - %s"%c)
    
    def command_view_all(self, channel, user, args):
        ''' View all relays in the config file '''
        self.notice(user, "Networks in the config file:")
        for x in self.factory.config.sections():
            if not x == "global_settings":
                self.notice(user, " - %s"%x)
    
    def command_add_channel(self, channel, user, args):
        ''' add_channel [network] [channel] (password)'''
        if not args or not len(args) >= 2: return self.notice(user, "Invalid arguments, use the help command")
        if not self.factory.networkExists(args[0]): return self.notice(user, "Unknown network %s, use list command"%args[0])
        try:
            password = args[2]
        except IndexError:
            password = None
        self.factory.AddChannel(args[0], args[1], password)
    
    def command_leave_channel(self, channel, user, args):
        ''' leave_channel [network] [channel] (reason...) '''
        if not args or not len(args) >= 2: return self.notice(user, "Invalid arguments, use the help command")
        if not self.factory.networkExists(args[0]): return self.notice(user, "Unknown network %s, use list command"%args[0])
        self.factory.LeaveChannel(args[0], args[1], " ".join(args[2:]))
    
    def command_add_network(self, channel, user, args):
        ''' add_network [identifier] [network_addr] [port] (Relaybot nickname)'''
        if not args or not len(args) >= 3: return self.notice(user, "Invalid arguments, use the help command")
        if self.factory.networkExists(args[1]): return self.notice(user, "Network %s already exists"%args[1])
        if not args[2].isdigit(): return self.notice(user, "Invalid port! Must be an integer")
        try:
            rnick = args[3]
        except:
            rnick = None
        self.factory.AddNetwork(args[0], args[1], int(args[2]), rnick)
    
    def command_remove_network(self, channel, user, args):
        ''' remove_network [host] - Remove a network from the config and disconnect it'''
        if not args: return self.notice(user, "Invalid arguments: use the help command")
        if not self.factory.networkExists(args[0]): return self.notice(user, "Invalid network, use the view_all command")
        self.factory.RemoveNetwork(args[0])

        
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
    

class HomeRelayManager(BaseFactory):
    protocol = IRCHomeRelayBot
    
    def __init__(self, manager, name, network, channel):
        self.manager = manager
        self.network = network
        self.channel = channel
        self.name = name
        self.terminated = False
    
    def buildProtocol(self, addr):
        x = self.protocol(self.manager, self.name, self.network, self.channel)
        x.factory = self
        return x


class RelayManagerFactory(BaseFactory):
    protocol = RelayManager
    def __init__(self, config, channel, network, port):
        self.config = config
        self.network = network
        self.port = port
        self.channel = channel
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
    
    def _makeHomeRelay(self, nick, network, channel):
        if not network in self.connectors:
            self.connectors[network] = []
        factory = HomeRelayManager(self, nick, network, channel)
        connector = internet.TCPClient(self.network, self.port, factory)
        connector.setServiceParent(application)
        self.connectors[network].append((connector,
                        factory))
    
    def _makeExternalRelay(self, nick, network, port, channels):
        if not network in self.connectors:
            self.connectors[network] = []
        factory = RelayFactory(self, nick, network, channels)
        connector = internet.TCPClient(network, port, factory)
        connector.setServiceParent(application)
        self.connectors[network].append((connector,
                        factory))
        
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
        self._makeHomeRelay(home_nick, external_network, self.channel)
        self._makeExternalRelay(external_nick or "RelayBot", external_network, 
                                external_port, external_channel)
        
    
    def AddNetwork(self, ident, network, port, nickname):
        self.config.add_section(network)
        config.set(network, "port", port)
        config.set(network, "ident", ident)
        config.set(network, "nickname", nickname or "")
        config.write(open("networks.ini","w"))
        
        self.SetupRelay(network, [], port, nickname, ident)
    
    def RemoveNetwork(self, network):
        log.msg("[Manager] Terminating relay")
        self.CallRelay(network, None, "Relay closing down")
        config.remove_section(network)
        config.write(open("networks.ini","w"))
        self.TerminateRelay(network)
    
    def AddChannel(self, network, chan, password):
        log.msg("[Manager] Adding channel %s to network %s"%(chan, network))
        config.set(network, "channel_"+chan, password or "")
        config.write(open("networks.ini","w"))
        self.CallTwoWay(network, chan, password, type="join")
    
    def LeaveChannel(self, network, chan, reason):
        log.msg("[Manager] Removing channel %s from network %s"%(chan, network))
        config.remove_option(network, "channel_"+chan)
        config.write(open("networks.ini","w"))
        self.CallTwoWay(network, chan, reason, type="leave")
    
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

    def AddUser(self, user):
        self.config.set("global_settings","user_"+user,"1")
        self.config.write(open("networks.ini","w"))
    
    def RemoveUser(self, user):
        if not self.UserIsAuthed(user):
            return False
        self.config.remove_option("global_settings","user_"+user)
        self.config.write(open("networks.ini","w"))
        return True
    
    def UserIsAuthed(self, user):
        return user in self.EnumerateUsers()
    
    def EnumerateUsers(self):
        r = []
        for x in config.options("global_settings"):
            if x.startswith("user_"):
                if not config.getint("global_settings",x): continue
                r.append(x.split("user_")[1])
        return r

application = service.Application("RelayBot") 

config = ConfigParser.ConfigParser()
config.read("networks.ini")
    
our_network = config.get("global_settings","network")
our_port    = config.getint("global_settings","port")
our_channel = (config.get("global_settings","channel"),
                   config.get("global_settings", "password"))
    
mangr = RelayManagerFactory(config, our_channel, our_network, our_port)
internet.TCPClient(our_network, our_port, mangr).setServiceParent(application)

for network in config.sections():
    if network == "global_settings": continue
    log.msg("[Config] Creating relay for network %s"%network)
        
    port, ident, nickname, channels = mangr.ReadNetworkSettings(network)
        
    mangr.SetupRelay(network, channels, port, nickname, ident)
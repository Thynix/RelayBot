from twisted.words.protocols import irc
from twisted.internet import reactor
from twisted.internet.protocol import ReconnectingClientFactory
from twisted.internet.task import LoopingCall
from twisted.python import log
from twisted.application import service
from signal import signal, SIGINT
from ConfigParser import SafeConfigParser
import sys
from tempfile import TemporaryFile
import subprocess

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
            if option in defaults or config.has_option(section, option):
                return config.get(section, option) or defaults[option]
            else:
                return None

        options = {}
        for option in ["timeout", "host", "port", "nick", "channel",
                       "heartbeat", "password", "username", "realname",
                       "recognizedNicks", "program", "useSSL"]:
            options[option] = get(option)

        mode = get("mode")

        #Not using endpoints pending http://twistedmatrix.com/trac/ticket/4735
        #(ReconnectingClientFactory equivalent for endpoints.)
        factory = None
        if mode == "Default":
            factory = RelayFactory
        elif mode == "NickServ":
            factory = NickServFactory
            options["nickServPassword"] = get("nickServPassword")
        factory = factory(options)
        reactor.connectTCP(options['host'], int(options['port']), factory, int(options['timeout']))

    reactor.callWhenRunning(signal, SIGINT, handler)


class IRCRelayer(irc.IRCClient):

    def __init__(self, config):
        self.network = config['host']
        self.password = config['password']
        self.channel = config['channel']
        self.nickname = config['nick']
        self.identifier = config['identifier']
        self.heartbeatInterval = float(config['heartbeat'])
        self.username = config['username']
        self.realname = config['realname']
        self.recognized_nicks = config['recognizedNicks'].split(',')
        self.program = config['program']

        log.msg("IRC Relay created. Name: {0} | Host: {1} | Channel: {2}"
                .format(self.nickname, self.network, self.channel))

        # IRC RFC: https://tools.ietf.org/html/rfc2812#page-4
        if len(self.nickname) > 9:
            log.msg("Nickname {0} is {1} characters long, which exceeds the "
                    "RFC maximum of 9 characters. This may cause connection "
                    "problems.".format(self.nickname, len(self.nickname)))

    def formatUsername(self, username):
        return username.split("!")[0]

    def signedOn(self):
        log.msg("[{0}] Connected to network.".format(self.network))
        self.startHeartbeat()
        self.join(self.channel, "")

    def connectionLost(self, reason):
        log.msg("[{0}] Connection lost: \"{1}\"".format(self.network, reason))

    def sayToChannel(self, message):
        self.say(self.channel, message)

    def joined(self, channel):
        log.msg("Joined channel {0}.".format(channel))

    def privmsg(self, user, channel, message):
        #If someone addresses the bot directly.
        if channel == self.nickname:
            if user in self.recognized_nicks:
                log.msg("Received privmsg from recognized {0}.".format(user))

                # Create input and output of processing program. StringIO
                # file objects are insufficient for these purposes -
                # apparently they must have real file descriptors.
                in_file = TemporaryFile()
                out_file = TemporaryFile()

                in_file.write(message)
                in_file.flush()

                ret_code = subprocess.call(self.program, stdin=in_file,
                                           stdout=out_file)

                if ret_code != 0:
                    self.msg(user, "Program {0} failed with return code {1}."
                             .format(self.program, ret_code))
                    return

                # Return output file to the beginning before reading.
                out_file.seek(0)

                for line in out_file:
                    self.msg(user, line)
            else:
                log.msg("Received privmsg from unrecognized {0}.".format(user))

    def kickedFrom(self, channel, kicker, message):
        log.msg("Kicked by {0}. Message \"{1}\"".format(kicker, message))


class RelayFactory(ReconnectingClientFactory):
    protocol = IRCRelayer
    #Log information which includes reconnection status.
    noisy = True

    def __init__(self, config):
        config["identifier"] = "{0}{1}{2}".format(config["host"], config["port"], config["channel"])
        config['useSSL'] = config['useSSL'] == 'True'
        self.config = config

    def buildProtocol(self, addr):
        #Connected - reset reconnect attempt delay.
        self.resetDelay()
        x = self.protocol(self.config)
        x.factory = self
        return x

class NickServRelayer(IRCRelayer):
    NickServ = "nickserv"
    NickPollInterval = 30

    def signedOn(self):
        log.msg("[{0}] Connected to network.".format(self.network))
        self.startHeartbeat()
        self.join(self.channel, "")
        self.checkDesiredNick()

    def checkDesiredNick(self):
        """
        Checks that the nick is as desired, and if not attempts to retrieve it with
        NickServ GHOST and trying again to change it after a polling interval.
        """
        if self.nickname != self.desiredNick:
            log.msg("[{0}] Using GHOST to reclaim nick {1}."
                    .format(self.network, self.desiredNick))
            self.msg(NickServRelayer.NickServ,
                     "GHOST {0} {1}".format(self.desiredNick, self.password))
            # If NickServ does not respond try to regain nick anyway.
            self.nickPoll.start(self.NickPollInterval)

    def regainNickPoll(self):
        if self.nickname != self.desiredNick:
            log.msg("[{0}] Reclaiming desired nick in polling."
                    .format(self.network))
            self.setNick(self.desiredNick)
        else:
            log.msg("[{0}] Have desired nick.".format(self.network))
            self.nickPoll.stop()

    def nickChanged(self, nick):
        log.msg("[{0}] Nick changed from {1} to {2}."
                .format(self.network, self.nickname, nick))
        self.nickname = nick
        self.checkDesiredNick()

    def noticed(self, user, channel, message):
        log.msg("[{0}] Received notice \"{1}\" from {2}."
                .format(self.network, message, user))

        #Identify with nickserv if requested
        if IRCRelayer.formatUsername(self, user).lower() == NickServRelayer.NickServ:
            msg = message.lower()
            if msg.startswith("this nickname is registered and protected"):
                log.msg("[{0}] Password requested; identifying with {1}."
                        .format(self.network, NickServRelayer.NickServ))
                self.msg(NickServRelayer.NickServ, "IDENTIFY {0}"
                         .format(self.password))
            elif msg == "ghost with your nickname has been killed."\
                    or msg == "ghost with your nick has been killed.":
                log.msg("[{0}] GHOST successful, reclaiming nick {1}."
                        .format(self.network, self.desiredNick))
                self.setNick(self.desiredNick)
            elif msg.endswith("isn't currently in use."):
                log.msg("[{0}] GHOST not needed, reclaiming nick {1}."
                        .format(self.network, self.desiredNick))
                self.setNick(self.desiredNick)

    def __init__(self, config):
        IRCRelayer.__init__(self, config)
        self.password = config['nickServPassword']
        self.desiredNick = config['nick']
        self.nickPoll = LoopingCall(self.regainNickPoll)


class NickServFactory(RelayFactory):
    protocol = NickServRelayer


def handler(signum, frame):
    reactor.stop()

#Main if run as script, builtin for twistd.
if __name__ in ["__main__", "__builtin__"]:
        main()

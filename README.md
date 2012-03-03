# RelayBot

A two-way IRC bridge bot in Python using [Twisted](http://twistedmatrix.com/trac/). It is based off of [relaybot](http://code.google.com/p/relaybot/), and aims to be less complicated by doing less.

This was written as I gutted `relaybot` while trying stop the second relay bot from failing to connect, preventing the relay from functioning. As such, it does not provide `relaybot`'s support for runtime configuration changes, multiple channels per host, or passworded channels. The design does not unduly impede the implementation of these abilities if need be. Unlike `relaybot`, `RelayBot` allows connecting to different ports on the same host simultaniously.

This distribution includes `run.sh` for easier control of the daemon.

## Requirements

 - Python 2.6.6-ish or higher
 - Twisted: `aptitude install python-twisted`

## Usage

Edit the sample config file as desired. If no local value exists for a section and the default is not defined, startup will fail.

`sh run.sh start`

## Internals

On startup, the config file is read, and for each section the local entry is preferred over the default one. For each defined host, an instance of `IRCRelay` or a subclass thereof (depending on `mode`) connects to the host and joins the channel. Each instance relays events to the others though a global `Communicator` class with which it registers. When the bot recieves a message, if it is to the channel it relays it, and if it is a private message to the bot it replies directly to the sender with the content of `info`. If a message to the channel starts with the bot's name followed by a colon, it announces `info` to the channel.

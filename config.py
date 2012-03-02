import os
import sys
import ConfigParser

if os.path.isfile("networks.ini"):
    print "[Error] networks.ini config file already exists, cannot continue"
    sys.exit(1)

config = ConfigParser.ConfigParser()
config.add_section("global_settings")
config.set("global_settings","network",raw_input("Your IRC servers hostname: "))
config.set("global_settings","port",raw_input("Your IRC servers port: "))
config.set("global_settings","channel",raw_input("Your channel (With #): "))
config.set("global_settings","password",raw_input("Your channels password (Leave blank for none): "))
print "Network setup complete. User setup:"
print "(All users set here have control over the RelayManager bot to add/remove networks etc)"
while True:
    user = raw_input("IRC username: ")
    config.set("global_settings","user_"+user,"1")
    if not raw_input("Add another user (y/n): ").lower() == "y":
        break

print "User setup complete. Writing config file..."
try:
    config.write(open("networks.ini","w"))
except Exception, e:
    print "[Error] Error writing config: %s"%e
    sys.exit(1)

print "Config written! Setup complete"
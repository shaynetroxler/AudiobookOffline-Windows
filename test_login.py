import getpass
import sys

sys.path.insert(0, ".")
from absplayer.client import ABSClient

server = input("Server URL [http://192.168.1.10:13378]: ") or "http://192.168.1.10:13378"
username = input("Username: ")
password = getpass.getpass("Password: ")

client, token = ABSClient.login(server, username, password)
print(f"\nLogged in. Token: {token[:12]}...")

libraries = client.libraries()
print(f"\nLibraries ({len(libraries)}):")
for lib in libraries:
    print(f"  - {lib.name} ({lib.media_type})")

if libraries:
    lib = libraries[0]
    items = client.items(lib.id, limit=5)
    print(f"\nFirst 5 items in '{lib.name}':")
    for item in items:
        print(f"  - {item.metadata.title} — {item.metadata.author_name}")

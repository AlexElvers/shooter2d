import asyncio
import json
import uuid
from typing import Dict

loop = asyncio.get_event_loop()


class Player:
    def __init__(self, x: float, y: float, rotation: float, health: float) -> None:
        self.x = x
        self.y = y
        self.rotation = rotation
        self.health = health

    def hit(self, damage: float) -> None:
        self.health = max(0, self.health - damage)


class World:
    def __init__(self):
        self.map = [
            "################",
            "#              #",
            "#              #",
            "#  ##########  #",
            "#  #        #  #",
            "#  #        #  #",
            "#  #  ####     #",
            "#        #     #",
            "#        ##  ###",
            "##     ####    #",
            "##     ####    #",
            "##     ######  #",
            "##     ######  #",
            "####           #",
            "####           #",
            "################",
        ]
        # self.map = [
        #     "     ",
        #     "     ",
        #     "  #  ",
        #     "     ",
        #     "     ",
        # ]
        # self.map_height = len(self.map)
        # self.map_width = len(self.map[0])
        # self.max_speed = 70
        # self.bullets: List[Bullet] = []
        # self.players: List[Player] = [
        #     Player(100, 150, -.3, .75),
        #     Player(675, 383, -.8, .15),
        # ]
        self.players: Dict[str, Player] = {}


class ServerClientProtocol(asyncio.Protocol):
    def __init__(self) -> None:
        self.uuid = str(uuid.uuid4())
        self.buffer = b""
        self.transport: asyncio.WriteTransport = None

    def send(self, **message) -> None:
        self.transport.write(json.dumps(message).encode() + b"\n")

    def send_others(self, **message) -> None:
        for client in clients.values():
            if client is not self:
                client.send(**message)

    def send_all(self, **message) -> None:
        for client in clients.values():
            client.send(**message)

    def connection_made(self, transport: asyncio.WriteTransport) -> None:
        self.transport = transport
        print(self.uuid, "connected")
        clients[self.uuid] = self
        world.players[self.uuid] = Player(400, 400, 0, 1)

        # send initial data
        self.send(type="world", map=world.map)
        self.send(type="uuid", uuid=self.uuid)

        self.send_all(type="players", players={
            uuid: (player.x, player.y, player.rotation, player.health) for uuid, player in world.players.items()
        })

    def connection_lost(self, exc):
        print("connection lost")
        del clients[self.uuid]
        del world.players[self.uuid]

        self.send_all(type="players", players={
            uuid: (player.x, player.y, player.rotation, player.health) for uuid, player in world.players.items()
        })

    def data_received(self, data: bytes) -> None:
        self.buffer += data

        while b"\n" in self.buffer:
            line, self.buffer = self.buffer.split(b"\n", 1)
            try:
                message = json.loads(line.decode())
                if not isinstance(message, dict):
                    raise json.JSONDecodeError
            except (UnicodeDecodeError, json.JSONDecodeError):
                print(self.uuid, f"received invalid data: {line!r}")
                self.send(type="error", error="invalid data")
                continue

            print("message:", message)

            message_type = message.get("type")
            if isinstance(message_type, str):
                handler = getattr(self, f"handle_{message_type}", None)
                if handler:
                    handler(message)
                else:
                    self.send(type="error", error=f"invalid message type: {message_type!r}")
            else:
                self.send(type="error", error="invalid message: type missing")

    def handle_position(self, message):
        x = message.get("x")
        y = message.get("y")
        rotation = message.get("rotation")
        if isinstance(x, float) and isinstance(y, float) and isinstance(rotation, float):
            world.players[self.uuid].x = x
            world.players[self.uuid].y = y
            world.players[self.uuid].rotation = rotation
            self.send_others(type="position", player=self.uuid, x=x, y=y, rotation=rotation)

    def handle_hit(self, message):
        uuid = message.get("player")
        strength = message.get("strength")
        if uuid in world.players:
            player = world.players[uuid]
            player.hit(strength)
            self.send_all(type="health", player=uuid, health=player.health)
        else:
            self.send(type="error", error=f"unknown uuid: {uuid!r}")


world = World()

clients: Dict[str, ServerClientProtocol] = {}
server = loop.run_until_complete(loop.create_server(ServerClientProtocol, "127.0.0.1", 5661))

try:
    loop.run_forever()
except KeyboardInterrupt:
    print("stopping server")

server.close()
loop.run_until_complete(server.wait_closed())
loop.close()

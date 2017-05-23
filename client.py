"""
Game
"""
import asyncio
import contextlib
import itertools
import json
import math
import time
from typing import List, Dict

import cairo
import gbulb
import gi

gi.require_version("Gtk", "3.0")
from gi.repository import Gtk, Gdk, GLib

gbulb.install(gtk=True)
loop = asyncio.get_event_loop()


@contextlib.contextmanager
def save_context(cr: cairo.Context) -> cairo.Context:
    cr.save()
    yield
    cr.restore()


class Rectangle:
    def __init__(self, left: float, right: float, top: float, bottom: float) -> None:
        self.left = left
        self.right = right
        self.top = top
        self.bottom = bottom
        self.width = right - left
        self.height = bottom - top
        self.x = left + self.width / 2
        self.y = top + self.height / 2


class Circle:
    def __init__(self, x: float, y: float, radius: float) -> None:
        self.x = x
        self.y = y
        self.radius = radius


class Player:
    def __init__(self, x: float, y: float, rotation: float, health: float) -> None:
        self.x = x
        self.y = y
        self.rotation = rotation
        self.health = health

    def hit(self, damage: float) -> None:
        self.health = max(0, self.health - damage)


class Bullet:
    def __init__(self, x: float, y: float, vx: float, vy: float) -> None:
        self.x = x
        self.y = y
        self.vx = vx
        self.vy = vy

    def animate(self, time_elapsed: float) -> None:
        self.x += time_elapsed * self.vx
        self.y += time_elapsed * self.vy


class ControlSettings:
    def __init__(self):
        self.pointer_based_movement = False


class WindowState:
    def __init__(self):
        self.pressed_keys = set()
        self.tick_time = time.perf_counter()
        self.pointer_x = 0
        self.pointer_y = 0


class World:
    def __init__(self):
        self.map: List[str] = None
        self.map_height: int = None
        self.map_width: int = None
        self.pos_x = 400
        self.pos_y = 400
        self.rotation = 0
        self.health = .65
        self.max_speed = 70
        self.bullets: List[Bullet] = []
        self.players: Dict[str, Player] = {
            "a": Player(100, 150, -.3, .75),
            "b": Player(675, 383, -.8, .15),
        }


def draw(widget: Gtk.Widget, cr: cairo.Context):
    if not world.map:
        return

    allocation = widget.get_allocation()
    tile_width = allocation.width / world.map_width
    tile_height = allocation.height / world.map_height

    # clear drawing
    cr.set_source_rgb(1, 1, 1)
    cr.paint()

    # draw shadow
    shadow_surface = cairo.ImageSurface(cairo.Format.ARGB32, allocation.width, allocation.height)
    scr = cairo.Context(shadow_surface)
    scr.set_line_width(1)
    scr.set_source_rgb(0, 0, 0)
    for y, row in enumerate(world.map):
        for x, tile in enumerate(row):
            if tile == "#":
                left = x * tile_width
                top = y * tile_height
                right = left + tile_width
                bottom = top + tile_height
                shadow_points = []
                for dest_x, dest_y in itertools.product([left, right], [top, bottom]):
                    other_x = {left: right, right: left}[dest_x]
                    other_y = {top: bottom, bottom: top}[dest_y]
                    if line_goes_through_border(world.pos_x, world.pos_y, dest_x, dest_y, other_x, top, bottom) \
                            or line_goes_through_border(world.pos_y, world.pos_x, dest_y, dest_x, other_y, left, right):
                        continue
                    shadow_points.append((dest_x, dest_y))
                if len(shadow_points) == 3:
                    for i in range(len(shadow_points)):
                        if shadow_points[i] == (shadow_points[(i - 1) % 3][0], shadow_points[(i + 1) % 3][1]) \
                                or shadow_points[i] == (shadow_points[(i + 1) % 3][0], shadow_points[(i - 1) % 3][1]):
                            del shadow_points[i]
                            break
                elif len(shadow_points) == 4:
                    continue
                for i, shadow_point in enumerate(extend_shadow_points(shadow_points, allocation)):
                    if i == 0:
                        scr.move_to(*shadow_point)
                    else:
                        scr.line_to(*shadow_point)
                scr.fill()
    cr.set_source_surface(shadow_surface)
    cr.mask(cairo.SolidPattern(0, 0, 0, .6))
    cr.fill()

    # draw tiles
    cr.set_line_width(1)
    for y, row in enumerate(world.map):
        for x, tile in enumerate(row):
            if tile == "#":
                cr.set_source_rgb(.9, 0, 0)
                cr.rectangle(x * tile_width, y * tile_height, tile_width, tile_height)
                cr.fill_preserve()
                cr.set_source_rgba(0, 0, 0)
                cr.stroke()

    for player in world.players.values():
        collides = False
        for y, row in enumerate(world.map):
            for x, tile in enumerate(row):
                if tile == "#":
                    left = x * tile_width
                    top = y * tile_height
                    right = left + tile_width
                    bottom = top + tile_height
                    if collision_rect_line(
                            Rectangle(left, right, top, bottom),
                            world.pos_x, world.pos_y, player.x, player.y):
                        collides = True
                        break
            if collides:
                break
        if not collides:
            draw_player(cr, player)

    draw_player(cr, Player(world.pos_x, world.pos_y, world.rotation, world.health))

    for bullet in world.bullets:
        draw_bullet(cr, bullet)


def extend_shadow_points(shadow_points, allocation):
    yield shadow_points[0]

    dx = shadow_points[0][0] - world.pos_x or 1e-10
    dy = shadow_points[0][1] - world.pos_y or 1e-10
    m = min([i for i in [
        (-world.pos_x) / dx,
        (allocation.width - world.pos_x) / dx,
        (-world.pos_y) / dy,
        (allocation.height - world.pos_y) / dy,
    ] if i > 0])
    extra1_x = world.pos_x + m * dx
    extra1_y = world.pos_y + m * dy

    dx = shadow_points[1][0] - world.pos_x or 1e-10
    dy = shadow_points[1][1] - world.pos_y or 1e-10
    m = min([i for i in [
        (-world.pos_x) / dx,
        (allocation.width - world.pos_x) / dx,
        (-world.pos_y) / dy,
        (allocation.height - world.pos_y) / dy,
    ] if i > 0])
    extra2_x = world.pos_x + m * dx
    extra2_y = world.pos_y + m * dy

    yield extra1_x, extra1_y

    extra3_x = None
    extra3_y = None
    if extra1_x < 1e-6 or extra1_x > allocation.width - 1e-6:
        extra3_x = extra1_x
    else:
        extra3_y = extra1_y
    if extra2_x < 1e-6 or extra2_x > allocation.width - 1e-6:
        if extra3_x is None:
            yield extra2_x, extra3_y
        elif abs(extra2_x - extra3_x) > 1e-6:
            yield extra3_x, 0 if dy < 0 else allocation.height
            yield extra2_x, 0 if dy < 0 else allocation.height
    else:
        if extra3_y is None:
            yield extra3_x, extra2_y
        elif abs(extra2_y - extra3_y) > 1e-6:
            yield 0 if dx < 0 else allocation.width, extra3_y
            yield 0 if dx < 0 else allocation.width, extra2_y

    yield extra2_x, extra2_y

    yield shadow_points[1]


def line_goes_through_border(pos1, pos2, dest1, dest2, border, lower, upper):
    """
    Test if the line from (pos1, pos2) to (dest1, dest2) goes through the border between lower and upper.
    """
    try:
        m = (border - pos1) / (dest1 - pos1)
    except ZeroDivisionError:
        return False
    wall_closer = 0 < m < 1
    through_wall = lower <= pos2 + m * (dest2 - pos2) <= upper
    return wall_closer and through_wall


def collision_rect_line(rect: Rectangle, start_x, start_y, end_x, end_y) -> bool:
    if line_goes_through_border(start_x, start_y, end_x, end_y, rect.left, rect.top, rect.bottom) \
            or line_goes_through_border(start_x, start_y, end_x, end_y, rect.right, rect.top, rect.bottom) \
            or line_goes_through_border(start_y, start_x, end_y, end_x, rect.top, rect.left, rect.right) \
            or line_goes_through_border(start_y, start_x, end_y, end_x, rect.bottom, rect.left, rect.right):
        return True
    return False


def collision_rect_circle(rect: Rectangle, circle: Circle) -> bool:
    dist_x = abs(circle.x - rect.x)
    dist_y = abs(circle.y - rect.y)

    if dist_x > rect.width / 2 + circle.radius:
        return False
    if dist_y > rect.height / 2 + circle.radius:
        return False

    if dist_x <= rect.width / 2:
        return True
    if dist_y <= rect.height / 2:
        return True

    corner_dist_sq = (dist_x - rect.width / 2)**2 + (dist_y - rect.height / 2)**2

    return corner_dist_sq <= circle.radius**2


def draw_player(cr: cairo.Context, player: Player) -> None:
    with save_context(cr):
        cr.translate(player.x, player.y)

        with save_context(cr):
            cr.rotate(player.rotation)

            # draw player
            cr.set_source_rgb(0, 0, 0)
            cr.arc(0, 0, 10, 0, math.tau)
            cr.fill()

            # draw arms
            cr.move_to(2, -10)
            cr.rel_line_to(12, 0)
            cr.move_to(2, 10)
            cr.rel_line_to(12, 0)
            cr.stroke()

        # draw health
        cr.set_source_rgb(1, 1, 1)
        cr.rectangle(-20, -35, 40, 8)
        cr.fill()
        # cr.set_source_rgb(.1, .9, .2)
        cr.set_source_rgb(2 * (1 - player.health), 2 * player.health, 0)
        cr.rectangle(-20, -35, 40 * player.health, 8)
        cr.fill()
        cr.set_line_width(1)
        cr.set_source_rgb(0, 0, 0)
        cr.rectangle(-20, -35, 40, 8)
        cr.stroke()


def draw_bullet(cr: cairo.Context, bullet: Bullet) -> None:
    cr.set_source_rgb(.2, .2, .2)
    cr.arc(bullet.x, bullet.y, 1, 0, math.tau)
    cr.fill()


def mouse_motion(widget: Gtk.Widget, event: Gdk.EventMotion):
    # world.pos_x = round(event.x)  # TODO we don't need round, just for testing purposes for the shadow
    # world.pos_y = round(event.y)
    window_state.pointer_x = event.x
    window_state.pointer_y = event.y
    world.rotation = math.atan2(window_state.pointer_y - world.pos_y, window_state.pointer_x - world.pos_x)
    widget.queue_draw()
    client_protocol.send(type="position", x=world.pos_x, y=world.pos_y, rotation=world.rotation)


def press_button(widget: Gtk.Widget, event: Gdk.EventButton):
    if event.type == Gdk.EventType.BUTTON_PRESS:
        dx = event.x - world.pos_x
        dy = event.y - world.pos_y
        norm = (dx**2 + dy**2)**.5
        world.bullets.append(Bullet(world.pos_x, world.pos_y, 500 * dx / norm, 500 * dy / norm))
    return True


def press_key(widget: Gtk.Widget, event: Gdk.EventKey):
    window_state.pressed_keys.add(Gdk.keyval_name(Gdk.keyval_to_lower(event.keyval)))
    tick()


def release_key(widget: Gtk.Widget, event: Gdk.EventKey):
    window_state.pressed_keys.discard(Gdk.keyval_name(Gdk.keyval_to_lower(event.keyval)))
    tick()


def handle_keys(time_elapsed):
    # move
    vx = 0
    vy = 0
    vx -= "a" in window_state.pressed_keys
    vx += "d" in window_state.pressed_keys
    vy -= "w" in window_state.pressed_keys
    vy += "s" in window_state.pressed_keys
    speed = world.max_speed
    if "Shift_L" in window_state.pressed_keys:
        speed /= 2
    if vx or vy:
        if control_settings.pointer_based_movement:
            # move in direction of the pointer
            cos = math.cos(self.rotation + math.pi / 2)
            sin = math.sin(self.rotation + math.pi / 2)
            vx, vy = cos * vx - sin * vy, sin * vx + cos * vy

        norm = (vx**2 + vy**2)**.5
        new_pos_x = world.pos_x + time_elapsed * speed * vx / norm
        new_pos_y = world.pos_y + time_elapsed * speed * vy / norm

        would_collide = False
        allocation = drawingarea.get_allocation()
        tile_width = allocation.width / world.map_width
        tile_height = allocation.height / world.map_height
        tile_x = int(world.pos_x / tile_width)
        tile_y = int(world.pos_y / tile_height)
        tile_x_lower = max(0, tile_x - 1)
        tile_x_upper = min(world.map_width, tile_x + 2)
        tile_y_lower = max(0, tile_y - 1)
        tile_y_upper = min(world.map_height, tile_y + 2)
        for y, row in enumerate(world.map[tile_y_lower:tile_y_upper], start=tile_y_lower):
            for x, tile in enumerate(row[tile_x_lower:tile_x_upper], start=tile_x_lower):
                if tile == "#":
                    left = x * tile_width
                    top = y * tile_height
                    right = left + tile_width
                    bottom = top + tile_height
                    if collision_rect_circle(
                            Rectangle(left, right, top, bottom),
                            Circle(new_pos_x, new_pos_y, 10)):
                        would_collide = True
                        break
            if would_collide:
                break

        if not would_collide:
            world.pos_x = new_pos_x
            world.pos_y = new_pos_y
            drawingarea.queue_draw()
            client_protocol.send(type="position", x=world.pos_x, y=world.pos_y, rotation=world.rotation)

    if "Up" in window_state.pressed_keys:
        world.health = min(1, world.health + time_elapsed * .2)
        drawingarea.queue_draw()
    if "Down" in window_state.pressed_keys:
        world.health = max(0, world.health - time_elapsed * .2)
        drawingarea.queue_draw()


def animate(time_elapsed):
    allocation = drawingarea.get_allocation()
    tile_width = allocation.width / world.map_width
    tile_height = allocation.height / world.map_height

    for bullet in world.bullets[:]:
        bullet.animate(time_elapsed)
        hit_someone = False
        for player in world.players.values():
            if (player.x - bullet.x)**2 + (player.y - bullet.y)**2 < 10**2:
                # hit
                player.hit(.1)
                hit_someone = True
        if hit_someone:
            world.bullets.remove(bullet)
        else:
            tile_x = int(bullet.x / tile_width)
            tile_y = int(bullet.y / tile_height)
            if 0 <= tile_x < world.map_width and 0 <= tile_y < world.map_height:
                if world.map[tile_y][tile_x] == "#":
                    world.bullets.remove(bullet)
        drawingarea.queue_draw()


def tick():
    current_time = time.perf_counter()
    time_elapsed = current_time - window_state.tick_time
    window_state.tick_time = current_time

    if not world.map:
        return True

    handle_keys(time_elapsed)
    animate(time_elapsed)

    return True


class ClientProtocol(asyncio.Protocol):
    def __init__(self) -> None:
        self.buffer = b""
        self.transport: asyncio.WriteTransport = None

    def send(self, **message) -> None:
        self.transport.write(json.dumps(message).encode() + b"\n")

    def connection_made(self, transport: asyncio.WriteTransport) -> None:
        self.transport = transport
        self.send(type="message")

    def connection_lost(self, exc) -> None:
        print("server closed connection")
        print("stop the event loop")
        loop.stop()

    def data_received(self, data: bytes) -> None:
        self.buffer += data

        while b"\n" in self.buffer:
            line, self.buffer = self.buffer.split(b"\n", 1)
            try:
                message = json.loads(line.decode())
            except (UnicodeDecodeError, json.JSONDecodeError):
                print(f"received invalid data: {line!r}")
                return

            message_type = message.get("type")
            if isinstance(message_type, str):
                handler = getattr(self, f"handle_{message_type}", None)
                if handler:
                    handler(message)
                else:
                    print(f"invalid message type: {message_type!r}")
            else:
                print("invalid message: type missing")

    def handle_error(self, message):
        print("error from server:", message["error"])

    def handle_world(self, message):
        world.map = message["map"]
        world.map_height = len(world.map)
        world.map_width = len(world.map[0])

    def handle_position(self, message):
        uuid = message["player"]
        if uuid not in world.players:
            world.players[uuid] = Player(message["x"], message["y"], message["rotation"], .5)
        else:
            world.players[uuid].x = message["x"]
            world.players[uuid].y = message["y"]
            world.players[uuid].rotation = message["rotation"]
            print("rotation", message["rotation"])
        drawingarea.queue_draw()


world = World()
window_state = WindowState()
control_settings = ControlSettings()

win = Gtk.Window(title="Game")
# win.connect("destroy", Gtk.main_quit)
win.connect("destroy", lambda *args: loop.stop())

drawingarea = Gtk.DrawingArea()
win.add(drawingarea)
drawingarea.connect("draw", draw)
drawingarea.add_events(Gdk.EventMask.POINTER_MOTION_MASK)
drawingarea.connect("motion-notify-event", mouse_motion)
drawingarea.set_size_request(800, 800)

win.connect("button-press-event", press_button)
win.connect("key-press-event", press_key)
win.connect("key-release-event", release_key)

tick_timeout = GLib.timeout_add(1, tick)

win.show_all()

client_transport, client_protocol = loop.run_until_complete(loop.create_connection(ClientProtocol, "127.0.0.1", 5661))

try:
    # Gtk.main()
    loop.run_forever()
except KeyboardInterrupt:
    pass

client_transport.close()
loop.close()

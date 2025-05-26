"""
war card game client and server
"""
import asyncio
from collections import namedtuple
from enum import Enum
import logging
import random
import socket
import socketserver
import threading
import sys


"""
Namedtuples work like classes, but are much more lightweight so they end
up being faster. It would be a good idea to keep objects in each of these
for each game which contain the game's state, for instance things like the
socket, the cards given, the cards still available, etc.
"""
Game = namedtuple("Game", ["p1", "p2"])

# Stores the clients waiting to get connected to other clients
waiting_clients = []


class Command(Enum):
    """
    The byte values sent as the first byte of any message in the war protocol.
    """
    WANTGAME = 0
    GAMESTART = 1
    PLAYCARD = 2
    PLAYRESULT = 3


class Result(Enum):
    """
    The byte values sent as the payload byte of a PLAYRESULT message.
    """
    WIN = 0
    DRAW = 1
    LOSE = 2

def readexactly(sock, numbytes):
    """
    Accumulate exactly `numbytes` from `sock` and return those. If EOF is found
    before numbytes have been received, be sure to account for that here or in
    the caller.
    """
    data = b''
    remaining = numbytes
    while remaining > 0:
        chunk = sock.recv(remaining)
        if not chunk:  # EOF reached
            return data  # Return what we have so far
        data += chunk
        remaining -= len(chunk)
    return data

def kill_game(game):
    """
    If either client sends a bad message, immediately nuke the game.
    """
    try:
        if game.p1:
            game.p1.close()
        if game.p2:
            game.p2.close()
        logging.debug("Game terminated")
    except Exception as e:
        logging.error(f"Error closing connections: {e}")

def compare_cards(card1, card2):
    """
    Given an integer card representation, return -1 for card1 < card2,
    0 for card1 = card2, and 1 for card1 > card2
    """
    # Cards are 0-51, with 0-12 being ranks of first suit, 13-25 being ranks of second suit, etc.
    # Extract the rank (mod 13) to compare
    rank1 = card1 % 13
    rank2 = card2 % 13
    
    if rank1 < rank2:
        return -1
    elif rank1 > rank2:
        return 1
    else:
        return 0
    

def deal_cards():
    """
    Randomize a deck of cards (list of ints 0..51), and return two
    26 card "hands."
    """
    # Create a deck of cards (0-51)
    deck = list(range(52))
    # Shuffle the deck
    random.shuffle(deck)
    # Split into two equal hands
    return deck[:26], deck[26:]
    

def serve_game(host, port):
    """
    Open a socket for listening for new connections on host:port, and
    perform the war protocol to serve a game of war between each client.
    This function should run forever, continually serving clients.
    """
    # Create a socket and bind it to the host and port
    server_socket = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
    server_socket.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
    server_socket.bind((host, port))
    server_socket.listen(5)
    logging.info(f"Server listening on {host}:{port}")
    
    # List to keep track of clients waiting for a game
    waiting_clients = []
    
    while True:
        try:
            # Accept a new client connection
            client_socket, client_addr = server_socket.accept()
            logging.debug(f"New connection from {client_addr}")
            
            # Read the client's first message
            msg = readexactly(client_socket, 2)
            if not msg or msg[0] != Command.WANTGAME.value:
                logging.warning(f"Invalid request from {client_addr}")
                client_socket.close()
                continue
            
            # If there's a client waiting, start a game
            if waiting_clients:
                # Get the waiting client
                player1 = waiting_clients.pop(0)
                player2 = client_socket
                
                # Create a new thread to handle the game
                game = Game(player1, player2)
                game_thread = threading.Thread(target=handle_game, args=(game,))
                game_thread.daemon = True
                game_thread.start()
            else:
                # No waiting clients, add to waiting list
                waiting_clients.append(client_socket)
                logging.debug(f"Client {client_addr} waiting for opponent")
        except Exception as e:
            logging.error(f"Error accepting connection: {e}")

def handle_game(game):
    """
    Handle a game between two clients
    """
    try:
        # Deal cards
        hand1, hand2 = deal_cards()
        
        # Send GAMESTART message with cards to both players
        p1_msg = bytes([Command.GAMESTART.value] + hand1)
        p2_msg = bytes([Command.GAMESTART.value] + hand2)
        game.p1.sendall(p1_msg)
        game.p2.sendall(p2_msg)
        
        # Play the game (26 rounds)
        for i in range(26):
            # Get card from player 1
            p1_play = readexactly(game.p1, 2)
            if not p1_play or p1_play[0] != Command.PLAYCARD.value:
                logging.warning("Invalid play from player 1")
                kill_game(game)
                return
            
            # Get card from player 2
            p2_play = readexactly(game.p2, 2)
            if not p2_play or p2_play[0] != Command.PLAYCARD.value:
                logging.warning("Invalid play from player 2")
                kill_game(game)
                return
            
            # Compare cards
            p1_card = p1_play[1]
            p2_card = p2_play[1]
            result = compare_cards(p1_card, p2_card)
            
            # Send results to both players
            if result > 0:
                # Player 1 wins
                game.p1.sendall(bytes([Command.PLAYRESULT.value, Result.WIN.value]))
                game.p2.sendall(bytes([Command.PLAYRESULT.value, Result.LOSE.value]))
            elif result < 0:
                # Player 2 wins
                game.p1.sendall(bytes([Command.PLAYRESULT.value, Result.LOSE.value]))
                game.p2.sendall(bytes([Command.PLAYRESULT.value, Result.WIN.value]))
            else:
                # Draw
                game.p1.sendall(bytes([Command.PLAYRESULT.value, Result.DRAW.value]))
                game.p2.sendall(bytes([Command.PLAYRESULT.value, Result.DRAW.value]))
        
        # Game complete
        logging.debug("Game completed successfully")
    except Exception as e:
        logging.error(f"Error during game: {e}")
        kill_game(game)
    finally:
        # Close connections
        try:
            game.p1.close()
            game.p2.close()
        except:
            pass
    

async def limit_client(host, port, loop, sem):
    """
    Limit the number of clients currently executing.
    You do not need to change this function.
    """
    async with sem:
        return await client(host, port, loop)

async def client(host, port, loop):
    """
    Run an individual client on a given event loop.
    You do not need to change this function.
    """
    try:
        reader, writer = await asyncio.open_connection(host, port)
        # send want game
        writer.write(b"\0\0")
        card_msg = await reader.readexactly(27)
        myscore = 0
        for card in card_msg[1:]:
            writer.write(bytes([Command.PLAYCARD.value, card]))
            result = await reader.readexactly(2)
            if result[1] == Result.WIN.value:
                myscore += 1
            elif result[1] == Result.LOSE.value:
                myscore -= 1
        if myscore > 0:
            result = "won"
        elif myscore < 0:
            result = "lost"
        else:
            result = "drew"
        logging.debug("Game complete, I %s", result)
        writer.close()
        return 1
    except ConnectionResetError:
        logging.error("ConnectionResetError")
        return 0
    except asyncio.IncompleteReadError:  # Changed from asyncio.streams.IncompleteReadError
        logging.error("asyncio.IncompleteReadError")
        return 0
    except OSError:
        logging.error("OSError")
        return 0

def main(args):
    """
    launch a client/server
    """
    host = args[1]
    port = int(args[2])
    if args[0] == "server":
        try:
            # your server should serve clients until the user presses ctrl+c
            serve_game(host, port)
        except KeyboardInterrupt:
            pass
        return
    else:
        try:
            loop = asyncio.get_running_loop()
        except RuntimeError:
            loop = asyncio.new_event_loop()
        
        asyncio.set_event_loop(loop)
        
    if args[0] == "client":
        loop.run_until_complete(client(host, port, loop))
    elif args[0] == "clients":
        sem = asyncio.Semaphore(1000)
        num_clients = int(args[3])
        clients = [limit_client(host, port, loop, sem)
                   for x in range(num_clients)]
        async def run_all_clients():
            """
            use `as_completed` to spawn all clients simultaneously
            and collect their results in arbitrary order.
            """
            completed_clients = 0
            for client_result in asyncio.as_completed(clients):
                completed_clients += await client_result
            return completed_clients
        res = loop.run_until_complete(
            asyncio.Task(run_all_clients(), loop=loop))
        logging.info("%d completed clients", res)

    loop.close()

if __name__ == "__main__":
    # Changing logging to DEBUG
    logging.basicConfig(level=logging.DEBUG)
    main(sys.argv[1:])

from flask import Flask, request, jsonify
import hashlib
import json
import time
import requests
import threading
from pymongo import MongoClient

app = Flask(__name__)

BLOCKCHAIN = []
NODES = set()
TOTAL_CIRCULATION = 100000
CURRENT_SUPPLY = 0
PORT = None  # Will be set dynamically

# Connect to MongoDB
MONGO_URI = "mongodb+srv://prorishab:prorishab@cluster0.0fmkg.mongodb.net/"
client = MongoClient(MONGO_URI)
db = client["test"]
posts_collection = db["posts"]
claims_collection = db["claims"]

def create_block(transactions, previous_hash):
    block = {
        'index': len(BLOCKCHAIN) + 1,
        'timestamp': time.time(),
        'transactions': transactions,
        'previous_hash': previous_hash,
    }
    return block

def hash_block(block):
    block_string = json.dumps(block, sort_keys=True).encode()
    return hashlib.sha256(block_string).hexdigest()

@app.route("/claim", methods=["GET"])
def claim():
    global CURRENT_SUPPLY

    key = request.args.get("key")
    password = request.args.get("password")
    coins_requested = request.args.get("coins")

    if not key or not password or not coins_requested:
        return jsonify({"error": "Invalid request. Provide key, password, and coins."}), 400

    try:
        coins_requested = int(coins_requested)
        if coins_requested <= 0:
            raise ValueError
    except ValueError:
        return jsonify({"error": "Invalid coins value. Must be a positive integer."}), 400

    post = posts_collection.find_one({"key": key})

    if not post:
        return jsonify({"error": "Post not found"}), 400

    num_likes = post.get("likes", 0)

    claimed_coins = 0
    for block in BLOCKCHAIN:
        for transaction in block["transactions"]:
            if transaction["key"] == key and transaction["password"] == password:
                claimed_coins += transaction["coins"]

    available_likes = num_likes - (claimed_coins * 10)
    max_claimable_coins = available_likes // 10  

    if max_claimable_coins < 1:
        return jsonify({"error": "Not enough new likes to claim coins"}), 400

    if coins_requested > max_claimable_coins:
        return jsonify({"error": f"You can claim a maximum of {max_claimable_coins} coins right now."}), 400

    if CURRENT_SUPPLY + coins_requested > TOTAL_CIRCULATION:
        return jsonify({"error": "Coin limit exceeded"}), 400

    transaction = {"key": key, "password": password, "coins": coins_requested}
    previous_hash = "0" if len(BLOCKCHAIN) == 0 else hash_block(BLOCKCHAIN[-1])
    block = create_block([transaction], previous_hash)

    approvals = validate_with_peers(block)

    if approvals < len(NODES) // 2:  
        return jsonify({"error": "Not enough peer approvals"}), 403

    BLOCKCHAIN.append(block)
    CURRENT_SUPPLY += coins_requested

    broadcast_block(block)

    return jsonify({"message": f"{coins_requested} coins claimed successfully!", "block": block}), 200

def validate_with_peers(block):
    approvals = 0
    print("peer validation happening")
    for node in NODES:
        try:
            response = requests.post(f"http://{node}/validate", json={"block": block})
            if response.status_code == 200:
                approvals += 1
        except requests.exceptions.RequestException:
            continue
    return approvals

@app.route("/validate", methods=["POST"])
def validate_block():
    block = request.json.get("block")
    if not block or "transactions" not in block:
        return jsonify({"error": "Invalid block format"}), 400

    transaction = block["transactions"][0]  
    key = transaction.get("key")
    password = transaction.get("password")
    coins = transaction.get("coins")

    if not key or not password or not coins:
        return jsonify({"error": "Invalid transaction data"}), 400

    post = posts_collection.find_one({"key": key})
    if not post:
        return jsonify({"error": "Post not found"}), 400

    num_likes = post.get("likes", 0)

    claim_record = claims_collection.find_one({"key": key})
    already_claimed_coins = claim_record.get("coins", 0) if claim_record else 0

    available_likes = num_likes - (already_claimed_coins * 10)
    max_claimable_coins = available_likes // 10

    if coins > max_claimable_coins:
        return jsonify({"error": "Claim exceeds available likes"}), 400

    return jsonify({"message": "Block approved"}), 200

@app.route("/chain", methods=["GET"])
def get_chain():
    return jsonify({"chain": BLOCKCHAIN}), 200

@app.route("/nodes/register", methods=["POST"])
def register_nodes():
    nodes = request.json.get("nodes")
    if not nodes:
        return jsonify({"error": "No nodes provided"}), 400

    for node in nodes:
        NODES.add(node)

    return jsonify({"message": "Nodes registered!", "total_nodes": list(NODES)}), 200

def broadcast_block(block):
    for node in NODES:
        try:
            requests.post(f"http://{node}/sync_block", json={"block": block})
        except requests.exceptions.RequestException:
            continue

@app.route("/sync_block", methods=["POST"])
def sync_block():
    block = request.json.get("block")
    if block:
        BLOCKCHAIN.append(block)
    return jsonify({"message": "Block synced"}), 200

def sync_blockchain():
    global BLOCKCHAIN
    longest_chain = BLOCKCHAIN
    for node in NODES:
        try:
            response = requests.get(f"http://{node}/chain")
            if response.status_code == 200:
                chain = response.json()["chain"]
                if len(chain) > len(longest_chain):
                    longest_chain = chain
        except requests.exceptions.RequestException:
            continue

    BLOCKCHAIN = longest_chain
    return {"message": "Blockchain synchronized!", "chain": BLOCKCHAIN}

@app.route("/nodes/sync", methods=["GET"])
def sync_chain_route():
    result = sync_blockchain()
    return jsonify(result), 200

def find_peers():
    """Continuously tries to find and register peers every 3 minutes"""
    global NODES
    base_peers = ["https://crypto-1-ru5c.onrender.com", "https://crypto-acun.onrender.com","https://crypto-2-xzzj.onrender.com"]

    while True:
        for peer in base_peers:
            if peer not in NODES:
                try:
                    response = requests.post(f"http://{peer}/nodes/register", json={"nodes": [f"localhost:{PORT}"]})
                    if response.status_code == 200:
                        NODES.add(peer)
                        print(f"🔗 Connected to peer {peer}")
                except requests.exceptions.RequestException:
                    print(f"⚠️ Could not connect to {peer}, retrying in 3 minutes...")

        time.sleep(180)  # Retry every 3 minutes

if __name__ == "__main__":
    import sys
    if len(sys.argv) != 2:
        print("Usage: python blockchain.py <port>")
        sys.exit(1)

    PORT = int(sys.argv[1])

    threading.Thread(target=find_peers, daemon=True).start()
    threading.Thread(target=sync_blockchain, daemon=True).start()

    app.run(port=PORT)

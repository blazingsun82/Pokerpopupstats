import os
import json
import asyncio
import re
from datetime import datetime
from typing import Dict, Any, List
from pathlib import Path
from io import BytesIO

from fastapi import FastAPI, Request, UploadFile, File, HTTPException
from fastapi.templating import Jinja2Templates
from fastapi.staticfiles import StaticFiles
from fastapi.responses import HTMLResponse, JSONResponse
from fastapi.middleware.cors import CORSMiddleware
from sse_starlette.sse import EventSourceResponse

app = FastAPI(title="Bingo Poker Pro's Awards Board", description="Tournament awards tracking system")

# Add CORS middleware for better browser compatibility
app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

# Templates and static files
templates = Jinja2Templates(directory="templates")

# Only mount static files if directory exists
if Path("static").exists():
    app.mount("/static", StaticFiles(directory="static"), name="static")

# Configuration - change this secret path!
SECRET_UPLOAD_PATH = os.getenv("UPLOAD_SECRET", "bingo-poker-secret-2025")
RESULTS_FILE = Path("results.json")

# SSE connection management
class SSEManager:
    def __init__(self):
        self._connections = []
    
    def add_connection(self, send_func):
        self._connections.append(send_func)
    
    def remove_connection(self, send_func):
        if send_func in self._connections:
            self._connections.remove(send_func)
    
    async def broadcast_update(self, data):
        dead_connections = []
        for send_func in self._connections[:]:
            try:
                await send_func({"event": "update", "data": json.dumps(data)})
            except:
                dead_connections.append(send_func)
        
        for dead_conn in dead_connections:
            self.remove_connection(dead_conn)

sse_manager = SSEManager()

# Awards calculation logic
class PokerAwardsParser:
    def parse_txt(self, content: bytes) -> Dict[str, Any]:
        """Parse poker text file and calculate awards"""
        try:
            print(f"Starting to parse file of size: {len(content)} bytes")
            players_data = self._extract_from_txt(content)
            print(f"Extracted data for {len([k for k in players_data.keys() if k != 'tournament_info'])} players")
            awards = self._calculate_awards(players_data)
            print(f"Calculated {len(awards)} awards")
            
            # Extract tournament info from players_data if available
            tournament_info = players_data.get('tournament_info', {})
            
            return {
                "tournament_date": tournament_info.get('date', datetime.now().strftime("%B %d, %Y at %I:%M %p")),
                "tournament_id": tournament_info.get('id', 'Unknown'),
                "total_players": tournament_info.get('player_count', len([p for p in players_data if p != 'tournament_info'])),
                "awards": awards,
                "last_updated": datetime.now().isoformat()
            }
        except Exception as e:
            print(f"Error parsing text file: {e}")
            import traceback
            traceback.print_exc()
            return self._generate_sample_data()
    
    def _extract_from_txt(self, content: bytes):
        """Extract player data from PokerStars text file"""
        # Convert bytes to text
        text = content.decode('utf-8')
        print(f"File content length: {len(text)} characters")
        print(f"First 200 characters: {text[:200]}")
        
        # Initialize data structures
        players = {}
        tournament_info = {}
        
        # Extract tournament information
        tournament_match = re.search(r'Tournament #(\d+)', text)
        if tournament_match:
            tournament_info['id'] = tournament_match.group(1)
            print(f"Found tournament ID: {tournament_info['id']}")
        else:
            print("No tournament ID found")
        
        date_match = re.search(r'(\d{4}/\d{2}/\d{2} \d{2}:\d{2}:\d{2})', text)
        if date_match:
            tournament_info['date'] = date_match.group(1)
            print(f"Found tournament date: {tournament_info['date']}")
        
        # FIXED REGEX - Extract all hands using PokerStars format
        hands = re.findall(r'(PokerStars Hand #\d+: Tournament #\d+.*?)(?=PokerStars Hand #\d+: Tournament #\d+|\Z)', text, re.DOTALL)
        print(f"Found {len(hands)} hands")
        
        if len(hands) > 0:
            print(f"First hand preview: {hands[0][:150]}...")
        else:
            print("WARNING: No hands found! File may not be in PokerStars tournament format")
            print("Looking for pattern starting with 'PokerStars Hand #'")
            # Try to find any PokerStars Hand mentions
            hand_mentions = re.findall(r'PokerStars Hand #\d+', text)
            print(f"Found {len(hand_mentions)} PokerStars Hand mentions")
            if hand_mentions:
                print(f"Example: {hand_mentions[0]}")
        
        for i, hand_text in enumerate(hands):
            if i < 3:  # Debug first few hands
                print(f"Processing hand {i+1}")
            self._parse_hand(hand_text, players)
        
        # Calculate final positions from chip counts and eliminations
        self._determine_final_positions(players, text)
        
        # Count total unique players
        tournament_info['player_count'] = len(players)
        print(f"Final player count: {tournament_info['player_count']}")
        
        # Store tournament info in the players dict for easy access
        players['tournament_info'] = tournament_info
        
        return players
    
    def _parse_hand(self, hand_text: str, players: Dict):
        """Parse individual hand and update player statistics"""
        # Extract players and their actions
        seat_pattern = r'Seat \d+: (\w+(?:\*\d+)?)\s*\((\d+) in chips\)'
        seats = re.findall(seat_pattern, hand_text)
        
        for player_name, chips in seats:
            if player_name not in players:
                players[player_name] = {
                    'hands_played': 0,
                    'raises': 0,
                    'calls': 0,
                    'folds': 0,
                    'bets': 0,
                    'checks': 0,
                    'showdowns': 0,
                    'showdown_wins': 0,
                    'total_won': 0,
                    'total_bet': 0,
                    'aggressive_actions': 0,
                    'passive_actions': 0,
                    'hands_voluntarily_played': 0,
                    'final_position': None,
                    'max_chips': int(chips),
                    'bad_beats': [],  # Store specific bad beat hands
                    'suckouts': []    # Store when they got lucky
                }
            
            players[player_name]['hands_played'] += 1
            players[player_name]['max_chips'] = max(players[player_name]['max_chips'], int(chips))
        
        # Analyze showdowns for bad beats
        if '*** SHOW DOWN ***' in hand_text:
            self._analyze_showdown_for_bad_beats(hand_text, players)
        
        # Count actions for each player
        action_patterns = {
            'raises': r'(\w+(?:\*\d+)?): raises',
            'calls': r'(\w+(?:\*\d+)?): calls',
            'folds': r'(\w+(?:\*\d+)?): folds',
            'bets': r'(\w+(?:\*\d+)?): bets',
            'checks': r'(\w+(?:\*\d+)?): checks'
        }
        
        for action_type, pattern in action_patterns.items():
            matches = re.findall(pattern, hand_text)
            for player in matches:
                if player in players:
                    players[player][action_type] += 1
                    
                    # Track aggressive vs passive actions
                    if action_type in ['raises', 'bets']:
                        players[player]['aggressive_actions'] += 1
                    elif action_type in ['calls', 'checks']:
                        players[player]['passive_actions'] += 1
        
        # Track voluntary play (not in blinds)
        voluntary_pattern = r'(\w+(?:\*\d+)?): (?:raises|calls|folds)(?! before Flop)'
        voluntary_players = set(re.findall(voluntary_pattern, hand_text))
        for player in voluntary_players:
            if player in players:
                players[player]['hands_voluntarily_played'] += 1
        
        # Track showdowns
        if '*** SHOW DOWN ***' in hand_text:
            showdown_pattern = r'(\w+(?:\*\d+)?): shows.*?and (won|lost)'
            showdown_matches = re.findall(showdown_pattern, hand_text)
            for player, result in showdown_matches:
                if player in players:
                    players[player]['showdowns'] += 1
                    if result == 'won':
                        players[player]['showdown_wins'] += 1
        
        # Track winnings
        collected_pattern = r'(\w+(?:\*\d+)?) collected (\d+) from pot'
        collected_matches = re.findall(collected_pattern, hand_text)
        for player, amount in collected_matches:
            if player in players:
                players[player]['total_won'] += int(amount)
    
    def _analyze_showdown_for_bad_beats(self, hand_text: str, players: Dict):
        """Analyze showdown hands to detect bad beats - when statistically favored hands lose"""
        # Extract board cards and showdown info
        board_match = re.search(r'Board \[([^\]]+)\]', hand_text)
        if not board_match:
            return
        
        board_cards = board_match.group(1).split()
        
        # Extract flop, turn, river progression
        flop_match = re.search(r'\*\*\* FLOP \*\*\* \[([^\]]+)\]', hand_text)
        turn_match = re.search(r'\*\*\* TURN \*\*\* \[([^\]]+)\] \[([^\]]+)\]', hand_text)
        river_match = re.search(r'\*\*\* RIVER \*\*\* \[([^\]]+)\] \[([^\]]+)\]', hand_text)
        
        # Extract showdown information
        showdown_section = hand_text.split('*** SHOW DOWN ***')[1] if '*** SHOW DOWN ***' in hand_text else ""
        
        # Pattern to match player showdowns with hands
        showdown_pattern = r'(\w+(?:\*\d+)?): shows \[([^\]]+)\] \(([^)]+)\) and (won|lost)'
        showdown_matches = re.findall(showdown_pattern, showdown_section)
        
        if len(showdown_matches) >= 2:
            # Find winner and analyze pre-flop hand strength
            winner = None
            loser = None
            winner_info = None
            loser_info = None
            
            for player, cards, hand_desc, result in showdown_matches:
                if result == 'won':
                    winner = player
                    winner_info = {'player': player, 'cards': cards, 'description': hand_desc}
                else:
                    loser = player
                    loser_info = {'player': player, 'cards': cards, 'description': hand_desc}
            
            if winner and loser and winner_info and loser_info:
                # Evaluate pre-flop hand strength
                winner_preflop_strength = self._evaluate_preflop_strength(winner_info['cards'])
                loser_preflop_strength = self._evaluate_preflop_strength(loser_info['cards'])
                
                # Check if this was a bad beat (stronger pre-flop hand lost)
                if loser_preflop_strength > winner_preflop_strength:
                    # Determine if it was a turn or river bad beat
                    bad_beat_street = "river"
                    if turn_match and river_match:
                        turn_card = river_match.group(2)
                        if self._hand_improved_on_street(winner_info['cards'], board_cards, turn_card):
                            bad_beat_street = "turn"
                    
                    bad_beat_info = {
                        'victim_hand': f"{loser_info['cards']} ({loser_info['description']})",
                        'winner_hand': f"{winner_info['cards']} ({winner_info['description']})",
                        'winner': winner,
                        'bad_beat_street': bad_beat_street,
                        'description': f"Lost {loser_info['description']} to {winner_info['description']} on the {bad_beat_street}",
                        'preflop_favorite': True
                    }
                    
                    if loser in players:
                        players[loser]['bad_beats'].append(bad_beat_info)
                    
                    # Track suckout for winner
                    if winner in players:
                        suckout_info = {
                            'winning_hand': f"{winner_info['cards']} ({winner_info['description']})",
                            'victim': loser,
                            'victim_hand': f"{loser_info['cards']} ({loser_info['description']})",
                            'suckout_street': bad_beat_street,
                            'description': f"Sucked out on the {bad_beat_street} with {winner_info['description']} vs {loser_info['description']}"
                        }
                        players[winner]['suckouts'].append(suckout_info)
    
    def _evaluate_preflop_strength(self, hole_cards: str) -> int:
        """Evaluate pre-flop hand strength for bad beat detection"""
        cards = hole_cards.strip().split()
        if len(cards) != 2:
            return 0
        
        # Parse cards
        card1_rank = cards[0][0]
        card1_suit = cards[0][1]
        card2_rank = cards[1][0]
        card2_suit = cards[1][1]
        
        # Convert face cards to numbers for easier comparison
        rank_values = {'2': 2, '3': 3, '4': 4, '5': 5, '6': 6, '7': 7, '8': 8, 
                      '9': 9, 'T': 10, 'J': 11, 'Q': 12, 'K': 13, 'A': 14}
        
        val1 = rank_values.get(card1_rank, 0)
        val2 = rank_values.get(card2_rank, 0)
        
        is_suited = card1_suit == card2_suit
        is_pair = val1 == val2
        
        # Premium hands (very strong pre-flop)
        if is_pair:
            if val1 >= 13:  # AA, KK
                return 100
            elif val1 >= 11:  # QQ, JJ
                return 90
            elif val1 >= 9:   # TT, 99
                return 80
            elif val1 >= 7:   # 88, 77
                return 70
            else:  # 66 and below
                return 60
        
        # Non-pair hands
        high_card = max(val1, val2)
        low_card = min(val1, val2)
        
        # AK, AQ type hands
        if high_card == 14:  # Ace
            if low_card >= 13:  # AK
                return 85 if is_suited else 80
            elif low_card >= 12:  # AQ
                return 75 if is_suited else 70
            elif low_card >= 11:  # AJ
                return 65 if is_suited else 60
            elif low_card >= 10:  # AT
                return 55 if is_suited else 50
            else:
                return 40 if is_suited else 30
        
        # King high hands
        elif high_card == 13:  # King
            if low_card >= 12:  # KQ
                return 65 if is_suited else 60
            elif low_card >= 11:  # KJ
                return 55 if is_suited else 50
            else:
                return 35 if is_suited else 25
        
        # Connected cards and suited connectors
        elif abs(val1 - val2) == 1:  # Connected
            return 45 if is_suited else 35
        elif abs(val1 - val2) == 2:  # One gap
            return 35 if is_suited else 25
        
        # Everything else
        return 20 if is_suited else 10
    
    def _hand_improved_on_street(self, hole_cards: str, board_cards: list, street_card: str) -> bool:
        """Check if a hand significantly improved on a specific street"""
        # This is a simplified check - in a full implementation you'd need
        # complete hand evaluation logic
        cards = hole_cards.strip().split()
        
        # Check if the street card matches hole cards (pair improvement)
        street_rank = street_card[0] if street_card else ''
        for card in cards:
            if card[0] == street_rank:
                return True
        
        # Additional checks for straights, flushes could be added here
        return False
    
    def _determine_final_positions(self, players: Dict, full_text: str):
        """Determine final tournament positions"""
        # Use chip counts as a proxy for positions
        chip_counts = [(name, data['max_chips']) for name, data in players.items() 
                      if name != 'tournament_info']
        chip_counts.sort(key=lambda x: x[1], reverse=True)
        
        for position, (player_name, chips) in enumerate(chip_counts, 1):
            players[player_name]['final_position'] = position
    
    def _calculate_awards(self, players_data: Dict[str, Dict]) -> Dict[str, Dict]:
        """Calculate fun club-style awards from parsed player data"""
        # Filter out tournament_info
        players = {k: v for k, v in players_data.items() if k != 'tournament_info'}
        
        if not players:
            print("No players found, returning sample awards")
            return self._get_sample_awards()
        
        print(f"Calculating awards for {len(players)} players")
        awards = {}
        
        # Tournament Champion (1st place)
        champion = min(players.items(), key=lambda x: x[1].get('final_position', 999))
        awards["🏆 Tournament Champion"] = {
            "winner": champion[0],
            "description": "Survived the chaos and claimed the crown",
            "stat": f"Outlasted {len(players)-1} other players"
        }
        
        # Runner Up (2nd place)
        second_place = min(players.items(), 
                          key=lambda x: x[1]['final_position'] if x[1]['final_position'] > 1 else 999)
        if second_place[1]['final_position'] <= len(players):
            awards["🥈 Runner Up"] = {
                "winner": second_place[0],
                "description": "So close to glory, yet so far",
                "stat": "Heads-up warrior"
            }
        
        # Preparation H Club (Bad Beat Victims)
        bad_beat_victims = [(name, data) for name, data in players.items() if data.get('bad_beats')]
        if bad_beat_victims:
            # Find the worst bad beat victim (most bad beats or worst individual beat)
            worst_victim = max(bad_beat_victims, key=lambda x: len(x[1]['bad_beats']))
            worst_beat = worst_victim[1]['bad_beats'][0] if worst_victim[1]['bad_beats'] else None
            
            awards["🩹 Preparation H Club"] = {
                "winner": worst_victim[0],
                "description": "Got unlucky when they were statistically favored to win",
                "stat": f"Had {worst_beat['victim_hand']} beaten by {worst_beat['winner_hand']} on the {worst_beat['bad_beat_street']}" if worst_beat else f"Suffered {len(worst_victim[1]['bad_beats'])} bad beats",
                "details": [beat['description'] for beat in worst_victim[1]['bad_beats'][:3]]  # Show up to 3 bad beats
            }
        
        # Luckiest Player (Most Suckouts)
        suckout_players = [(name, data) for name, data in players.items() if data.get('suckouts')]
        if suckout_players:
            luckiest = max(suckout_players, key=lambda x: len(x[1]['suckouts']))
            best_suckout = luckiest[1]['suckouts'][0] if luckiest[1]['suckouts'] else None
            
            awards["🍀 Luckiest (Suckout King)"] = {
                "winner": luckiest[0],
                "description": "Got incredibly lucky when it mattered most",
                "stat": f"Won with {best_suckout['winning_hand']} against {best_suckout['victim_hand']}" if best_suckout else "Multiple suckouts delivered",
                "details": [suckout['description'] for suckout in luckiest[1]['suckouts'][:3]]
            }
        
        # Most Aggressive (highest aggression ratio)
        aggressive_players = [(name, data) for name, data in players.items() 
                            if data['hands_played'] > 5]
        if aggressive_players:
            most_aggressive = max(aggressive_players, 
                                key=lambda x: x[1]['aggressive_actions'] / max(x[1]['hands_played'], 1))
            awards["🔥 Most Aggressive"] = {
                "winner": most_aggressive[0],
                "description": "Fearless bets and raises kept everyone on edge",
                "stat": "Never met a pot they didn't want to steal"
            }
        
        # Calling Station
        if aggressive_players:
            calling_station = max(aggressive_players,
                                key=lambda x: x[1]['calls'] / max(x[1]['hands_played'], 1))
            awards["📞 Calling Station"] = {
                "winner": calling_station[0],
                "description": "Never saw a bet they didn't want to call",
                "stat": "The human slot machine"
            }
        
        # Tightest Player (Rock Award)
        if aggressive_players:
            tightest = min(aggressive_players,
                         key=lambda x: x[1]['hands_voluntarily_played'] / max(x[1]['hands_played'], 1))
            awards["🧊 Tightest (Rock Award)"] = {
                "winner": tightest[0],
                "description": "Waited patiently for the premiums",
                "stat": "Classic rock-solid play"
            }
        
        # Donkey (most hands played)
        action_player = max(players.items(), key=lambda x: x[1]['hands_played'])
        awards["🐴 Donkey"] = {
            "winner": action_player[0],
            "description": "Played way too many hands, couldn't fold to save their life",
            "stat": f"Played {action_player[1]['hands_played']} hands"
        }
        
        # ABC Player (predictable, straightforward play)
        if aggressive_players:
            abc_candidates = [(name, data) for name, data in aggressive_players
                            if 0.15 < (data['aggressive_actions'] / data['hands_played']) < 0.35]
            if abc_candidates:
                abc_player = max(abc_candidates, 
                               key=lambda x: x[1].get('showdown_wins', 0))
                awards["📚 ABC Player"] = {
                    "winner": abc_player[0],
                    "description": "Played textbook poker, predictable as clockwork",
                    "stat": "By-the-book basic strategy"
                }
        
        # Biggest Bluffer
        bluffer_candidates = [(name, data) for name, data in players.items() 
                            if data.get('bets', 0) > 2]
        if bluffer_candidates:
            bluffer = max(bluffer_candidates,
                        key=lambda x: x[1]['bets'] / max(x[1].get('showdowns', 1), 1))
            awards["🎭 Biggest Bluffer"] = {
                "winner": bluffer[0],
                "description": "Firing barrels with air, keeping the table guessing",
                "stat": "Master of the poker face"
            }
        
        # Bubble Boy (if enough players)
        if len(players) >= 4:
            bubble_position = (len(players) + 1) // 2
            bubble_candidates = [p for p in players.items() 
                               if p[1].get('final_position') == bubble_position]
            if bubble_candidates:
                awards["💀 Bubble Boy"] = {
                    "winner": bubble_candidates[0][0],
                    "description": "Knocked out just before the money in heartbreaking fashion",
                    "stat": "So close to cashing, yet so far"
                }
        
        return awards
    
    def _get_sample_awards(self):
        """Return fun sample awards when no real data"""
        return {
            "🏆 Tournament Champion": {
                "winner": "Blazingsun81", 
                "description": "Survived the chaos and claimed the crown", 
                "stat": "Outlasted 5 other players"
            },
            "🩹 Preparation H Club": {
                "winner": "Sick Nickel",
                "description": "Got unlucky when they were statistically favored to win",
                "stat": "Had pocket aces cracked by 7-2 offsuit on the river",
                "details": ["Lost AA vs 72o when villain hit two pair", "Had KK beaten by A3 when ace hit the turn", "Flopped a set, lost to runner-runner flush"]
            },
            "🔥 Most Aggressive": {
                "winner": "Fuzzy Nips", 
                "description": "Fearless bets and raises kept everyone on edge", 
                "stat": "Never met a pot they didn't want to steal"
            },
            "🍀 Luckiest (Suckout King)": {
                "winner": "Kentie Boy", 
                "description": "Got incredibly lucky when it mattered most", 
                "stat": "Won with 72 offsuit against pocket aces on the river",
                "details": ["Rivered two pair with 72o vs AA", "Hit a 2-outer on the turn for the win", "Sucked out with gutshot straight on river"]
            },
            "📞 Calling Station": {
                "winner": "Esk", 
                "description": "Never saw a bet they didn't want to call", 
                "stat": "The human slot machine"
            },
            "🎭 Biggest Bluffer": {
                "winner": "Trofimuk", 
                "description": "Firing barrels with air, keeping the table guessing", 
                "stat": "Master of the poker face"
            }
        }
    
    def _generate_sample_data(self):
        """Fallback sample data"""
        return {
            "tournament_date": datetime.now().strftime("%B %d, %Y at %I:%M %p"),
            "tournament_id": "3928736979",
            "total_players": 6,
            "awards": self._get_sample_awards(),
            "last_updated": datetime.now().isoformat()
        }

parser = PokerAwardsParser()

# Load existing results
def load_results():
    if RESULTS_FILE.exists():
        try:
            with open(RESULTS_FILE, 'r') as f:
                return json.load(f)
        except:
            pass
    return parser._generate_sample_data()

def save_results(data):
    with open(RESULTS_FILE, 'w') as f:
        json.dump(data, f, indent=2)

# Routes
@app.get("/", response_class=HTMLResponse)
async def public_board(request: Request):
    """Public awards board - no upload capability"""
    results = load_results()
    return templates.TemplateResponse("board.html", {
        "request": request,
        "results": results,
        "is_public": True
    })

@app.get(f"/upload/{SECRET_UPLOAD_PATH}", response_class=HTMLResponse)
async def upload_page(request: Request):
    """Secret upload page - drag & drop interface"""
    results = load_results()
    return templates.TemplateResponse("upload.html", {
        "request": request,
        "results": results,
        "upload_url": f"/upload/{SECRET_UPLOAD_PATH}/process"
    })

@app.post(f"/upload/{SECRET_UPLOAD_PATH}/process")
async def process_upload(file: UploadFile = File(...)):
    """Process the uploaded TXT file"""
    print(f"Received file upload: {file.filename}")
    print(f"File content type: {file.content_type}")
    
    if not file.filename.endswith('.txt'):
        print(f"Rejected file: not a .txt file")
        raise HTTPException(400, "Please upload a TXT file")
    
    try:
        # Read TXT content
        content = await file.read()
        print(f"Read {len(content)} bytes from uploaded file")
        
        # Parse and calculate awards
        results = parser.parse_txt(content)
        print(f"Parsing complete. Results: {results}")
        
        # Save results
        save_results(results)
        print("Results saved successfully")
        
        # Broadcast to all connected clients
        await sse_manager.broadcast_update(results)
        print("Broadcast update sent")
        
        return {"success": True, "message": "Awards updated successfully!", "results": results}
    
    except Exception as e:
        print(f"Error in process_upload: {str(e)}")
        import traceback
        traceback.print_exc()
        raise HTTPException(500, f"Error processing file: {str(e)}")

@app.get("/events")
async def stream_events(request: Request):
    """SSE endpoint for real-time updates"""
    async def event_stream():
        # Send current data immediately
        current_data = load_results()
        yield {"event": "init", "data": json.dumps(current_data)}
        
        # Create a queue for this connection
        queue = asyncio.Queue()
        
        async def sender(event_data):
            await queue.put(event_data)
        
        sse_manager.add_connection(sender)
        
        try:
            while True:
                # Wait for new events
                event_data = await queue.get()
                yield event_data
        except asyncio.CancelledError:
            pass
        finally:
            sse_manager.remove_connection(sender)
    
    return EventSourceResponse(event_stream())

if __name__ == "__main__":
    import uvicorn
    uvicorn.run(app, host="0.0.0.0", port=8000)

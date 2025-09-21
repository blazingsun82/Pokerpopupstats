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
        """Analyze showdown hands to detect bad beats"""
        # Extract showdown information
        showdown_section = hand_text.split('*** SHOW DOWN ***')[1] if '*** SHOW DOWN ***' in hand_text else ""
        
        # Pattern to match player showdowns with hands
        showdown_pattern = r'(\w+(?:\*\d+)?): shows \[([^\]]+)\] \(([^)]+)\)'
        showdown_matches = re.findall(showdown_pattern, showdown_section)
        
        if len(showdown_matches) >= 2:
            # Find winner
            winner_pattern = r'(\w+(?:\*\d+)?) collected \d+ from pot'
            winner_match = re.search(winner_pattern, hand_text)
            winner = winner_match.group(1) if winner_match else None
            
            # Analyze each showdown hand
            hand_strengths = []
            for player, cards, hand_desc in showdown_matches:
                strength = self._evaluate_hand_strength(hand_desc)
                hand_strengths.append({
                    'player': player,
                    'cards': cards,
                    'description': hand_desc,
                    'strength': strength,
                    'won': player == winner
                })
            
            # Sort by hand strength (higher is better)
            hand_strengths.sort(key=lambda x: x['strength'], reverse=True)
            
            # Check for bad beats (weaker hand beats stronger hand)
            if len(hand_strengths) >= 2 and winner:
                winner_strength = next((h['strength'] for h in hand_strengths if h['player'] == winner), 0)
                
                for hand_info in hand_strengths:
                    if hand_info['player'] != winner and hand_info['strength'] > winner_strength:
                        # This is a bad beat victim
                        bad_beat_info = {
                            'victim_hand': f"{hand_info['cards']} ({hand_info['description']})",
                            'winner_hand': f"{next(h['cards'] for h in hand_strengths if h['player'] == winner)} ({next(h['description'] for h in hand_strengths if h['player'] == winner)})",
                            'winner': winner,
                            'description': f"Lost with {hand_info['description']} to {next(h['description'] for h in hand_strengths if h['player'] == winner)}"
                        }
                        
                        if hand_info['player'] in players:
                            players[hand_info['player']]['bad_beats'].append(bad_beat_info)
                        
                        # Track suckout for winner
                        if winner in players:
                            suckout_info = {
                                'winning_hand': f"{next(h['cards'] for h in hand_strengths if h['player'] == winner)} ({next(h['description'] for h in hand_strengths if h['player'] == winner)})",
                                'victim': hand_info['player'],
                                'victim_hand': f"{hand_info['cards']} ({hand_info['description']})",
                                'description': f"Sucked out with {next(h['description'] for h in hand_strengths if h['player'] == winner)} against {hand_info['description']}"
                            }
                            players[winner]['suckouts'].append(suckout_info)
    
    def _evaluate_hand_strength(self, hand_description: str) -> int:
        """Evaluate poker hand strength for bad beat detection"""
        hand_desc = hand_description.lower()
        
        # Hand rankings (higher number = stronger hand)
        if 'royal flush' in hand_desc:
            return 10
        elif 'straight flush' in hand_desc:
            return 9
        elif 'four of a kind' in hand_desc or 'quads' in hand_desc:
            return 8
        elif 'full house' in hand_desc:
            return 7
        elif 'flush' in hand_desc:
            return 6
        elif 'straight' in hand_desc:
            return 5
        elif 'three of a kind' in hand_desc or 'trips' in hand_desc:
            return 4
        elif 'two pair' in hand_desc:
            return 3
        elif 'pair' in hand_desc:
            return 2
        else:
            return 1  # High card
    
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
            # Find the worst bad beat victim
            worst_victim = max(bad_beat_victims, key=lambda x: len(x[1]['bad_beats']))
            worst_beat = worst_victim[1]['bad_beats'][0] if worst_victim[1]['bad_beats'] else None
            
            awards["🩹 Preparation H Club"] = {
                "winner": worst_victim[0],
                "description": "Suffered the most painful bad beats of the night",
                "stat": f"Lost with {worst_beat['victim_hand']} to {worst_beat['winner_hand']}" if worst_beat else "Multiple bad beats endured",
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
                "description": "Suffered the most painful bad beats of the night",
                "stat": "Lost with AK suited to 72 offsuit",
                "details": ["Lost with pocket aces to a rivered two pair", "Flopped a set, lost to runner-runner flush"]
            },
            "🔥 Most Aggressive": {
                "winner": "Fuzzy Nips", 
                "description": "Fearless bets and raises kept everyone on edge", 
                "stat": "Never met a pot they didn't want to steal"
            },
            "🍀 Luckiest (Suckout King)": {
                "winner": "Kentie Boy", 
                "description": "Got incredibly lucky when it mattered most", 
                "stat": "Won with 72 offsuit against pocket aces",
                "details": ["Rivered a straight with 54 against top pair", "Hit a two-outer on the turn for the win"]
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

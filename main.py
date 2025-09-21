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
SECRET_UPLOAD_PATH = os.getenv("UPLOAD_SECRET", "poker-club-2025-upload")
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
            players_data = self._extract_from_txt(content)
            awards = self._calculate_awards(players_data)
            
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
            return self._generate_sample_data()
    
    def _extract_from_txt(self, content: bytes):
        """Extract player data from PokerStars text file"""
        # Convert bytes to text
        text = content.decode('utf-8')
        
        # Initialize data structures
        players = {}
        tournament_info = {}
        
        # Extract tournament information
        tournament_match = re.search(r'Tournament #(\d+)', text)
        if tournament_match:
            tournament_info['id'] = tournament_match.group(1)
        
        date_match = re.search(r'(\d{4}/\d{2}/\d{2} \d{2}:\d{2}:\d{2})', text)
        if date_match:
            tournament_info['date'] = date_match.group(1)
        
        # Extract all hands
        hands = re.findall(r'\*{11} # \d+ \*{14}(.*?)(?=\*{11} # \d+ \*{14}|\Z)', text, re.DOTALL)
        
        for hand_text in hands:
            self._parse_hand(hand_text, players)
        
        # Calculate final positions from chip counts and eliminations
        self._determine_final_positions(players, text)
        
        # Count total unique players
        tournament_info['player_count'] = len(players)
        
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
                    'max_chips': int(chips)
                }
            
            players[player_name]['hands_played'] += 1
            players[player_name]['max_chips'] = max(players[player_name]['max_chips'], int(chips))
        
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
            return self._get_sample_awards()
        
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
        
        # Luckiest Player
        showdown_players = [(name, data) for name, data in players.items() 
                          if data.get('showdowns', 0) >= 2]
        if showdown_players:
            luckiest = max(showdown_players,
                         key=lambda x: x[1]['showdown_wins'] / max(x[1]['showdowns'], 1))
            awards["🍀 Luckiest"] = {
                "winner": luckiest[0],
                "description": "Turned trash into treasure at showdown",
                "stat": "The poker gods were smiling"
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
        
        # Bad Beat Victim (unlucky at showdown)
        if showdown_players:
            bad_beat_victim = min(showdown_players,
                                key=lambda x: x[1]['showdown_wins'] / max(x[1]['showdowns'], 1))
            win_rate = (bad_beat_victim[1]['showdown_wins'] / bad_beat_victim[1]['showdowns']) * 100
            awards["💔 Bad Beat Victim"] = {
                "winner": bad_beat_victim[0],
                "description": "The poker gods showed no mercy tonight",
                "stat": f"{win_rate:.0f}% showdown win rate"
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
            "🔥 Most Aggressive": {
                "winner": "Fuzzy Nips", 
                "description": "Fearless bets and raises kept everyone on edge", 
                "stat": "Never met a pot they didn't want to steal"
            },
            "🍀 Luckiest": {
                "winner": "Sick Nickel", 
                "description": "Turned trash into treasure at showdown", 
                "stat": "The poker gods were smiling"
            },
            "🧊 Tightest (Rock Award)": {
                "winner": "Esk", 
                "description": "Waited patiently for the premiums", 
                "stat": "Classic rock-solid play"
            },
            "📞 Calling Station": {
                "winner": "Kentie Boy", 
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
    if not file.filename.endswith('.txt'):
        raise HTTPException(400, "Please upload a TXT file")
    
    try:
        # Read TXT content
        content = await file.read()
        
        # Parse and calculate awards
        results = parser.parse_txt(content)
        
        # Save results
        save_results(results)
        
        # Broadcast to all connected clients
        await sse_manager.broadcast_update(results)
        
        return {"success": True, "message": "Awards updated successfully!", "results": results}
    
    except Exception as e:
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
    uvicorn.run(app, host="0.0.0.0", port=8000)import os
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
SECRET_UPLOAD_PATH = os.getenv("UPLOAD_SECRET", "poker-club-2025-upload")
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
            players_data = self._extract_from_txt(content)
            awards = self._calculate_awards(players_data)
            
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
            return self._generate_sample_data()
    
    def _extract_from_txt(self, content: bytes):
        """Extract player data from PokerStars text file"""
        # Convert bytes to text
        text = content.decode('utf-8')
        
        # Initialize data structures
        players = {}
        tournament_info = {}
        
        # Extract tournament information
        tournament_match = re.search(r'Tournament #(\d+)', text)
        if tournament_match:
            tournament_info['id'] = tournament_match.group(1)
        
        date_match = re.search(r'(\d{4}/\d{2}/\d{2} \d{2}:\d{2}:\d{2})', text)
        if date_match:
            tournament_info['date'] = date_match.group(1)
        
        # Extract all hands
        hands = re.findall(r'\*{11} # \d+ \*{14}(.*?)(?=\*{11} # \d+ \*{14}|\Z)', text, re.DOTALL)
        
        for hand_text in hands:
            self._parse_hand(hand_text, players)
        
        # Calculate final positions from chip counts and eliminations
        self._determine_final_positions(players, text)
        
        # Count total unique players
        tournament_info['player_count'] = len(players)
        
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
                    'max_chips': int(chips)
                }
            
            players[player_name]['hands_played'] += 1
            players[player_name]['max_chips'] = max(players[player_name]['max_chips'], int(chips))
        
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
            return self._get_sample_awards()
        
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
        
        # Luckiest Player
        showdown_players = [(name, data) for name, data in players.items() 
                          if data.get('showdowns', 0) >= 2]
        if showdown_players:
            luckiest = max(showdown_players,
                         key=lambda x: x[1]['showdown_wins'] / max(x[1]['showdowns'], 1))
            awards["🍀 Luckiest"] = {
                "winner": luckiest[0],
                "description": "Turned trash into treasure at showdown",
                "stat": "The poker gods were smiling"
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
        
        # Bad Beat Victim (unlucky at showdown)
        if showdown_players:
            bad_beat_victim = min(showdown_players,
                                key=lambda x: x[1]['showdown_wins'] / max(x[1]['showdowns'], 1))
            win_rate = (bad_beat_victim[1]['showdown_wins'] / bad_beat_victim[1]['showdowns']) * 100
            awards["💔 Bad Beat Victim"] = {
                "winner": bad_beat_victim[0],
                "description": "The poker gods showed no mercy tonight",
                "stat": f"{win_rate:.0f}% showdown win rate"
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
            "🔥 Most Aggressive": {
                "winner": "Fuzzy Nips", 
                "description": "Fearless bets and raises kept everyone on edge", 
                "stat": "Never met a pot they didn't want to steal"
            },
            "🍀 Luckiest": {
                "winner": "Sick Nickel", 
                "description": "Turned trash into treasure at showdown", 
                "stat": "The poker gods were smiling"
            },
            "🧊 Tightest (Rock Award)": {
                "winner": "Esk", 
                "description": "Waited patiently for the premiums", 
                "stat": "Classic rock-solid play"
            },
            "📞 Calling Station": {
                "winner": "Kentie Boy", 
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
    if not file.filename.endswith('.txt'):
        raise HTTPException(400, "Please upload a TXT file")
    
    try:
        # Read TXT content
        content = await file.read()
        
        # Parse and calculate awards
        results = parser.parse_txt(content)
        
        # Save results
        save_results(results)
        
        # Broadcast to all connected clients
        await sse_manager.broadcast_update(results)
        
        return {"success": True, "message": "Awards updated successfully!", "results": results}
    
    except Exception as e:
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

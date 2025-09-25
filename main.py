import os
import json
import asyncio
import re
from datetime import datetime
from typing import Dict, Any, List
from pathlib import Path
from io import BytesIO

from fastapi import FastAPI, Request, UploadFile, File, HTTPException, Form
from fastapi.templating import Jinja2Templates
from fastapi.staticfiles import StaticFiles
from fastapi.responses import HTMLResponse, JSONResponse, RedirectResponse
from fastapi.middleware.cors import CORSMiddleware
from sse_starlette.sse import EventSourceResponse

# PostgreSQL imports
import psycopg2
from psycopg2.extras import RealDictCursor

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
ADMIN_SECRET_PATH = os.getenv("ADMIN_SECRET", "admin-control-2025")
RESULTS_FILE = Path("results.json")
DATABASE_URL = os.getenv("DATABASE_URL")

# Debug: Print the upload path
print(f"Upload path configured as: /upload/{SECRET_UPLOAD_PATH}")
print(f"Admin path configured as: /admin/{ADMIN_SECRET_PATH}")

# Add environment variable to store results as backup
def save_to_env_backup(data):
    """Save critical data to environment variable as backup"""
    try:
        # Store key data in environment variable for persistence
        backup_data = {
            "tournament_date": data.get("tournament_date"),
            "tournament_id": data.get("tournament_id"),
            "awards": data.get("awards", {}),
            "preparation_h_club": data.get("preparation_h_club", [])
        }
        os.environ["POKER_RESULTS_BACKUP"] = json.dumps(backup_data)
    except Exception as e:
        print(f"Failed to save backup: {e}")

def load_from_env_backup():
    """Load results from environment variable backup"""
    try:
        backup_str = os.environ.get("POKER_RESULTS_BACKUP")
        if backup_str:
            return json.loads(backup_str)
    except Exception as e:
        print(f"Failed to load backup: {e}")
    return None

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

# PostgreSQL Database Functions
def get_db_connection():
    """Get database connection"""
    if not DATABASE_URL:
        raise Exception("DATABASE_URL not configured")
    return psycopg2.connect(DATABASE_URL)

def init_database():
    """Initialize database tables"""
    try:
        conn = get_db_connection()
        cur = conn.cursor()
        
        # Create player_points table
        cur.execute('''
            CREATE TABLE IF NOT EXISTS player_points (
                player_name VARCHAR(100) PRIMARY KEY,
                total_points DECIMAL(10,2) DEFAULT 0,
                avatar VARCHAR(50) DEFAULT '',
                tournaments_played INTEGER DEFAULT 0,
                last_updated TIMESTAMP DEFAULT CURRENT_TIMESTAMP
            )
        ''')
        
        # Create points_history table for audit trail
        cur.execute('''
            CREATE TABLE IF NOT EXISTS points_history (
                id SERIAL PRIMARY KEY,
                player_name VARCHAR(100),
                tournament_date VARCHAR(50),
                points_change DECIMAL(10,2),
                action_type VARCHAR(50),
                timestamp TIMESTAMP DEFAULT CURRENT_TIMESTAMP
            )
        ''')
        
        conn.commit()
        cur.close()
        conn.close()
        print("Database initialized successfully")
    except Exception as e:
        print(f"Database initialization error: {e}")

def get_all_player_points():
    """Get all player points ordered by total"""
    try:
        conn = get_db_connection()
        cur = conn.cursor(cursor_factory=RealDictCursor)
        cur.execute('''
            SELECT player_name, total_points, avatar, tournaments_played
            FROM player_points
            ORDER BY total_points DESC
        ''')
        results = cur.fetchall()
        cur.close()
        conn.close()
        return results
    except Exception as e:
        print(f"Error fetching player points: {e}")
        return []

def update_player_points(player_name: str, points: float, tournament_date: str):
    """Add points to player's total"""
    try:
        conn = get_db_connection()
        cur = conn.cursor()
        
        # Upsert player points
        cur.execute('''
            INSERT INTO player_points (player_name, total_points, tournaments_played)
            VALUES (%s, %s, 1)
            ON CONFLICT (player_name) 
            DO UPDATE SET 
                total_points = player_points.total_points + %s,
                tournaments_played = player_points.tournaments_played + 1,
                last_updated = CURRENT_TIMESTAMP
        ''', (player_name, points, points))
        
        # Record in history
        cur.execute('''
            INSERT INTO points_history (player_name, tournament_date, points_change, action_type)
            VALUES (%s, %s, %s, 'tournament_result')
        ''', (player_name, tournament_date, points))
        
        conn.commit()
        cur.close()
        conn.close()
        return True
    except Exception as e:
        print(f"Error updating player points: {e}")
        return False

def edit_player_points(player_name: str, new_total: float, reason: str):
    """Manually edit player's total points"""
    try:
        conn = get_db_connection()
        cur = conn.cursor()
        
        # Get current points
        cur.execute('SELECT total_points FROM player_points WHERE player_name = %s', (player_name,))
        result = cur.fetchone()
        old_total = result[0] if result else 0
        
        # Update total
        cur.execute('''
            INSERT INTO player_points (player_name, total_points)
            VALUES (%s, %s)
            ON CONFLICT (player_name)
            DO UPDATE SET total_points = %s, last_updated = CURRENT_TIMESTAMP
        ''', (player_name, new_total, new_total))
        
        # Record in history
        cur.execute('''
            INSERT INTO points_history (player_name, tournament_date, points_change, action_type)
            VALUES (%s, %s, %s, %s)
        ''', (player_name, reason, new_total - old_total, 'manual_edit'))
        
        conn.commit()
        cur.close()
        conn.close()
        return True
    except Exception as e:
        print(f"Error editing player points: {e}")
        return False

def reset_all_points():
    """Reset all player points to zero"""
    try:
        conn = get_db_connection()
        cur = conn.cursor()
        
        # Archive current data to history
        cur.execute('''
            INSERT INTO points_history (player_name, tournament_date, points_change, action_type)
            SELECT player_name, 'season_reset', -total_points, 'season_reset'
            FROM player_points
            WHERE total_points > 0
        ''')
        
        # Reset all points
        cur.execute('UPDATE player_points SET total_points = 0, tournaments_played = 0')
        
        conn.commit()
        cur.close()
        conn.close()
        return True
    except Exception as e:
        print(f"Error resetting points: {e}")
        return False

# Initialize database on startup
if DATABASE_URL:
    init_database()
else:
    print("WARNING: DATABASE_URL not set - points tracking disabled")

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
            
            # Extract bad beat victims for separate section
            preparation_h_club = self._extract_preparation_h_club(players_data)
            
            result = {
                "tournament_date": tournament_info.get('date', datetime.now().strftime("%B %d, %Y at %I:%M %p")),
                "tournament_id": tournament_info.get('id', 'Unknown'),
                "total_players": tournament_info.get('player_count', len([p for p in players_data if p != 'tournament_info'])),
                "awards": awards,
                "preparation_h_club": preparation_h_club,
                "last_updated": datetime.now().isoformat()
            }
            
            return result
        except Exception as e:
            print(f"Error parsing text file: {e}")
            import traceback
            traceback.print_exc()
            return self._generate_sample_data()
    
    def _extract_preparation_h_club(self, players_data: Dict[str, Dict]) -> List[Dict]:
        """Extract bad beat victims for the Preparation H Club section"""
        preparation_h_club = []
        
        # Filter out tournament_info
        players = {k: v for k, v in players_data.items() if k != 'tournament_info'}
        
        for player_name, player_data in players.items():
            bad_beats = player_data.get('bad_beats', [])
            for bad_beat in bad_beats:
                preparation_h_club.append({
                    'victim': player_name,
                    'victim_hand': bad_beat['victim_hand'],
                    'winner': bad_beat['winner'],
                    'winner_hand': bad_beat['winner_hand'],
                    'description': bad_beat['description']
                })
        
        print(f"DEBUG: Created Preparation H Club with {len(preparation_h_club)} bad beats")
        return preparation_h_club
    
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
        
        # Debug: Check how many hands have showdowns
        showdown_count = 0
        for hand in hands:
            if '*** SHOW DOWN ***' in hand:
                showdown_count += 1
        print(f"DEBUG: Found {showdown_count} hands with showdowns out of {len(hands)} total hands")
        
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
                # Check if this hand has a showdown
                if '*** SHOW DOWN ***' in hand_text:
                    print(f"DEBUG: Hand {i+1} contains a showdown")
                else:
                    print(f"DEBUG: Hand {i+1} has no showdown")
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
            print(f"DEBUG: Found showdown in hand")
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
        """Analyze showdown hands to detect genuine bad beats - when strong made hands lose"""
        try:
            if '*** SHOW DOWN ***' not in hand_text:
                return
                
            # Extract showdown section
            showdown_section = hand_text.split('*** SHOW DOWN ***')[1]
            print(f"DEBUG: Found showdown section: {showdown_section[:200]}...")
            
            # Find all players who showed hands
            showdown_pattern = r'(\w+(?:\*\d+)?): shows \[([^\]]+)\] \(([^)]+)\)'
            showdown_matches = re.findall(showdown_pattern, showdown_section)
            
            # Find who won the pot
            winner_pattern = r'(\w+(?:\*\d+)?) collected (\d+) from pot'
            winner_match = re.search(winner_pattern, hand_text)
            winner = winner_match.group(1) if winner_match else None
            
            print(f"DEBUG: Showdown found - {len(showdown_matches)} players showed hands, winner: {winner}")
            
            # Only analyze hands where both players showed (for clear bad beat identification)
            if len(showdown_matches) >= 2 and winner:
                player_hands = []
                for player, cards, hand_desc in showdown_matches:
                    try:
                        made_hand_strength = self._evaluate_made_hand_strength(hand_desc)
                        player_hands.append({
                            'player': player,
                            'cards': cards,
                            'description': hand_desc,
                            'made_hand_strength': made_hand_strength,
                            'won': player == winner
                        })
                        print(f"DEBUG: {player} showed {cards} ({hand_desc}) - made hand strength: {made_hand_strength}")
                    except Exception as e:
                        print(f"DEBUG: Error processing player {player}: {e}")
                        continue
                
                # Find strong hands that lost
                losing_hands = [h for h in player_hands if not h['won']]
                winning_hand = next((h for h in player_hands if h['won']), None)
                
                if losing_hands and winning_hand:
                    # Check for genuine bad beats - strong made hands losing to weaker ones or miracle draws
                    for losing_hand in losing_hands:
                        try:
                            if self._is_genuine_bad_beat(losing_hand, winning_hand):
                                victim_name = losing_hand['player']
                                victim_desc = self._get_simple_hand_description(losing_hand['description'])
                                winner_desc = self._get_simple_hand_description(winning_hand['description'])
                                
                                # Create clear, simple description
                                description = f"{victim_name} had {victim_desc}, got cracked by {winner}'s {winner_desc}"
                                
                                print(f"DEBUG: GENUINE BAD BEAT! {description}")
                                
                                bad_beat_info = {
                                    'victim_hand': losing_hand['description'],
                                    'winner_hand': winning_hand['description'],
                                    'winner': winner,
                                    'description': description
                                }
                                
                                if victim_name in players:
                                    players[victim_name]['bad_beats'].append(bad_beat_info)
                                    print(f"DEBUG: Added bad beat to {victim_name}")
                                
                                # Track suckout for winner
                                if winner in players:
                                    suckout_info = {
                                        'winning_hand': winning_hand['description'],
                                        'victim': victim_name,
                                        'victim_hand': losing_hand['description'],
                                        'description': f"Sucked out with {winner_desc} vs {victim_desc}"
                                    }
                                    players[winner]['suckouts'].append(suckout_info)
                                    print(f"DEBUG: Added suckout to {winner}")
                        except Exception as e:
                            print(f"DEBUG: Error processing bad beat for {losing_hand['player']}: {e}")
                            continue
                            
        except Exception as e:
            print(f"DEBUG: Error in bad beat analysis: {e}")
            return
    
    def _evaluate_made_hand_strength(self, hand_description: str) -> int:
        """Evaluate the strength of a made hand for bad beat detection"""
        hand_desc = hand_description.lower()
        
        # Royal flush and straight flush
        if 'royal flush' in hand_desc:
            return 1000
        elif 'straight flush' in hand_desc:
            return 900
        
        # Four of a kind (quads)
        elif 'four of a kind' in hand_desc:
            return 800
        
        # Full house
        elif 'full house' in hand_desc:
            return 700
        
        # Flush
        elif 'flush' in hand_desc and 'straight' not in hand_desc:
            return 600
        
        # Straight
        elif 'straight' in hand_desc and 'flush' not in hand_desc:
            return 500
        
        # Three of a kind (trips/set)
        elif 'three of a kind' in hand_desc:
            return 400
        
        # Two pair
        elif 'two pair' in hand_desc:
            # Strong two pair (high cards)
            if any(card in hand_desc for card in ['aces', 'kings', 'queens']):
                return 300
            else:
                return 200
        
        # One pair
        elif 'pair of' in hand_desc:
            # High pairs are stronger
            if 'aces' in hand_desc:
                return 150
            elif 'kings' in hand_desc:
                return 140
            elif 'queens' in hand_desc:
                return 130
            elif 'jacks' in hand_desc:
                return 120
            else:
                return 100
        
        # High card
        else:
            return 50
    
    def _is_genuine_bad_beat(self, losing_hand: Dict, winning_hand: Dict) -> bool:
        """Determine if this qualifies as a genuine bad beat"""
        loser_strength = losing_hand['made_hand_strength']
        winner_strength = winning_hand['made_hand_strength']
        
        # Bad beat criteria:
        # 1. Loser had a reasonably strong hand (trips or better)
        # 2. Winner had a stronger hand but got there with luck
        # 3. OR loser had very strong hand (full house+) and lost to anything better
        
        # Strong hands that should qualify as bad beat victims
        if loser_strength >= 400:  # Three of a kind or better
            return True
        
        # Very strong two pair can be bad beats too
        if loser_strength >= 300 and winner_strength > loser_strength:
            return True
        
        return False
    
    def _get_simple_hand_description(self, full_description: str) -> str:
        """Convert full poker description to simple terms"""
        desc = full_description.lower()
        
        if 'royal flush' in desc:
            return 'royal flush'
        elif 'straight flush' in desc:
            return 'straight flush'
        elif 'four of a kind' in desc:
            # Extract the rank
            if 'aces' in desc:
                return 'quad aces'
            elif 'kings' in desc:
                return 'quad kings'
            elif 'queens' in desc:
                return 'quad queens'
            else:
                return 'quads'
        elif 'full house' in desc:
            return 'full house'
        elif 'flush' in desc and 'straight' not in desc:
            return 'flush'
        elif 'straight' in desc and 'flush' not in desc:
            return 'straight'
        elif 'three of a kind' in desc:
            if 'aces' in desc:
                return 'trip aces'
            elif 'kings' in desc:
                return 'trip kings'
            elif 'queens' in desc:
                return 'trip queens'
            elif 'jacks' in desc:
                return 'trip jacks'
            else:
                return 'trips'
        elif 'two pair' in desc:
            return 'two pair'
        elif 'pair of aces' in desc:
            return 'pocket aces'
        elif 'pair of kings' in desc:
            return 'pocket kings'
        elif 'pair of queens' in desc:
            return 'pocket queens'
        elif 'pair of jacks' in desc:
            return 'pocket jacks'
        elif 'pair of' in desc:
            return 'a pair'
    def _is_likely_runner_runner(self, description: str, suckout_info: Dict) -> bool:
        """Determine if this was likely a runner-runner (backdoor) win"""
        # This is a simplified check - in a real implementation, we'd need to parse
        # the actual board texture and hole cards to definitively identify runner-runner
        
        # Look for patterns that suggest backdoor draws
        runner_runner_indicators = [
            'flush' in description and 'straight' not in description,  # Backdoor flush
            'straight' in description and 'flush' not in description,  # Backdoor straight
        ]
        
        # Check if the winning hand type suggests a possible runner-runner
        winning_hand = suckout_info.get('winning_hand', '').lower()
        victim_hand = suckout_info.get('victim_hand', '').lower()
        
        # Simple heuristic: if winner made flush/straight and victim had pair/two pair
        if ('flush' in winning_hand and ('pair' in victim_hand or 'two pair' in victim_hand)):
            return True
        elif ('straight' in winning_hand and ('pair' in victim_hand or 'two pair' in victim_hand)):
            return True
            
        return False
    
    def _evaluate_preflop_strength(self, hole_cards: str) -> int:
        """Evaluate pre-flop hand strength - kept for compatibility"""
        cards = hole_cards.strip().split()
        if len(cards) != 2:
            return 0
        
        # Parse cards
        card1_rank = cards[0][0] if len(cards[0]) > 0 else '2'
        card2_rank = cards[1][0] if len(cards[1]) > 0 else '2'
        
        # Convert face cards to numbers for easier comparison
        rank_values = {'2': 2, '3': 3, '4': 4, '5': 5, '6': 6, '7': 7, '8': 8, 
                      '9': 9, 'T': 10, 'J': 11, 'Q': 12, 'K': 13, 'A': 14}
        
        val1 = rank_values.get(card1_rank, 0)
        val2 = rank_values.get(card2_rank, 0)
        
        if val1 == val2:  # Pair
            if val1 >= 13:  # AA, KK
                return 100
            elif val1 >= 11:  # QQ, JJ
                return 90
            elif val1 >= 9:   # TT, 99
                return 80
            else:
                return 70
        
        # Non-pair hands
        high_card = max(val1, val2)
        if high_card == 14:  # Ace high
            return 80
        elif high_card >= 12:  # King or Queen high
            return 60
        else:
            return 40
    
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
        
        # REMOVED: Preparation H Club is now handled separately in the bottom section only
        
        # Runner-Runner Win (needed both turn and river to make hand)
        runner_runner_players = []
        for name, data in players.items():
            suckouts = data.get('suckouts', [])
            for suckout in suckouts:
                # Look for descriptions that suggest runner-runner scenarios
                description = suckout.get('description', '').lower()
                if self._is_likely_runner_runner(description, suckout):
                    runner_runner_players.append((name, suckout))
        
        if runner_runner_players:
            # Pick the most impressive runner-runner win
            best_runner_runner = runner_runner_players[0]  # For now, take the first one
            player_name = best_runner_runner[0]
            suckout_info = best_runner_runner[1]
            
            awards["🎯 Runner-Runner Win"] = {
                "winner": player_name,
                "description": "Needed both turn and river cards to complete their hand",
                "stat": f"Hit the perfect two-card combination to win"
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
        
        # Donkey (poor decision making - high VPIP with low success rate)
        # Look for players who play too many hands with poor results
        donkey_candidates = []
        for name, data in players.items():
            if data['hands_played'] > 10:  # Need sufficient sample size
                vpip = data['hands_voluntarily_played'] / data['hands_played']
                win_rate = data.get('showdown_wins', 0) / max(data.get('showdowns', 1), 1)
                
                # Donkey criteria: plays too many hands (high VPIP) with poor results
                if vpip > 0.4 and win_rate < 0.3:  # Plays 40%+ hands but wins <30% at showdown
                    donkey_score = vpip / (win_rate + 0.1)  # Higher score = more donkey-like
                    donkey_candidates.append((name, data, donkey_score))
        
        # Only award if there's a clear donkey (someone significantly worse than others)
        if donkey_candidates:
            donkey_candidates.sort(key=lambda x: x[2], reverse=True)
            worst_player = donkey_candidates[0]
            
            # Only give award if they're clearly playing poorly (not just unlucky)
            if worst_player[2] > 1.5:  # Threshold for clear donkey behavior
                awards["🐴 Donkey"] = {
                    "winner": worst_player[0],
                    "description": "Made questionable decisions and played too many weak hands",
                    "stat": f"Played {int(worst_player[1]['hands_voluntarily_played'] / worst_player[1]['hands_played'] * 100)}% of hands with poor results"
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
                "winner": "Player1", 
                "description": "Survived the chaos and claimed the crown", 
                "stat": "Outlasted 5 other players"
            },
            "🔥 Most Aggressive": {
                "winner": "Player2", 
                "description": "Fearless bets and raises kept everyone on edge", 
                "stat": "Never met a pot they didn't want to steal"
            },
            "🍀 Luckiest (Suckout King)": {
                "winner": "Player3", 
                "description": "Got incredibly lucky when it mattered most", 
                "stat": "Won with 72 offsuit against pocket aces",
                "details": ["Rivered a straight with 54 against top pair", "Hit a two-outer on the turn for the win"]
            },
            "📞 Calling Station": {
                "winner": "Player4", 
                "description": "Never saw a bet they didn't want to call", 
                "stat": "The human slot machine"
            },
            "🎭 Biggest Bluffer": {
                "winner": "Player5", 
                "description": "Firing barrels with air, keeping the table guessing", 
                "stat": "Master of the poker face"
            }
        }
    
    def _generate_sample_data(self):
        """Fallback sample data with separate preparation H club"""
        return {
            "tournament_date": datetime.now().strftime("%B %d, %Y at %I:%M %p"),
            "tournament_id": "3928736979",
            "total_players": 6,
            "awards": self._get_sample_awards(),
            "preparation_h_club": [],  # Empty array - no hardcoded bad beats
            "last_updated": datetime.now().isoformat()
        }

parser = PokerAwardsParser()

# Load existing results with backup system
def load_results():
    # First try to load from file
    if RESULTS_FILE.exists():
        try:
            with open(RESULTS_FILE, 'r') as f:
                data = json.load(f)
                # Save to backup when successfully loaded
                save_to_env_backup(data)
                return data
        except Exception as e:
            print(f"Failed to load from file: {e}")
    
    # If file doesn't exist or failed, try backup
    backup_data = load_from_env_backup()
    if backup_data:
        print("Loaded from environment backup")
        # Reconstruct full data structure
        return {
            "tournament_date": backup_data.get("tournament_date", datetime.now().strftime("%B %d, %Y at %I:%M %p")),
            "tournament_id": backup_data.get("tournament_id", "Unknown"),
            "total_players": len(backup_data.get("awards", {})),
            "awards": backup_data.get("awards", {}),
            "preparation_h_club": backup_data.get("preparation_h_club", []),
            "last_updated": datetime.now().isoformat()
        }
    
    # If no backup, use sample data
    print("No existing data found, using sample data")
    return parser._generate_sample_data()

def save_results(data):
    # Always save backup to environment FIRST
    save_to_env_backup(data)
    
    # Save to file
    try:
        with open(RESULTS_FILE, 'w') as f:
            json.dump(data, f, indent=2)
        print("Successfully saved to both file and environment backup")
    except Exception as e:
        print(f"Failed to save to file: {e}")
        print("Data is still saved in environment backup")

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
        
        # Clear any old environment backup before saving new data
        if "POKER_RESULTS_BACKUP" in os.environ:
            del os.environ["POKER_RESULTS_BACKUP"]
            print("Cleared old environment backup")
        
        # Save results with backup
        save_results(results)
        print("Results saved successfully (with backup)")
        
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

# Points Management Routes
@app.get("/leaderboard", response_class=HTMLResponse)
async def leaderboard(request: Request):
    """Display points leaderboard"""
    players = get_all_player_points()
    return templates.TemplateResponse("leaderboard.html", {
        "request": request,
        "players": players
    })

@app.post(f"/upload/{SECRET_UPLOAD_PATH}/points")
async def upload_points(file: UploadFile = File(...), tournament_date: str = Form(...)):
    """Process uploaded points file"""
    if not file.filename.endswith('.txt'):
        raise HTTPException(400, "Please upload a TXT file")
    
    try:
        content = await file.read()
        text = content.decode('utf-8')
        
        # Parse points file - format: "PlayerName: X.XX points" per line
        lines = text.strip().split('\n')
        updated_count = 0
        
        for line in lines:
            # Simple parsing - adjust based on actual file format
            if ':' in line:
                parts = line.split(':')
                if len(parts) >= 2:
                    player_name = parts[0].strip()
                    points_str = parts[1].strip().replace('points', '').replace('pts', '').strip()
                    try:
                        points = float(points_str)
                        if update_player_points(player_name, points, tournament_date):
                            updated_count += 1
                    except ValueError:
                        continue
        
        return {"success": True, "message": f"Updated {updated_count} players", "players_updated": updated_count}
    
    except Exception as e:
        raise HTTPException(500, f"Error processing points file: {str(e)}")

@app.get(f"/admin/{ADMIN_SECRET_PATH}", response_class=HTMLResponse)
async def admin_panel(request: Request):
    """Admin control panel"""
    players = get_all_player_points()
    return templates.TemplateResponse("admin.html", {
        "request": request,
        "players": players,
        "admin_path": ADMIN_SECRET_PATH
    })

@app.post(f"/admin/{ADMIN_SECRET_PATH}/edit")
async def admin_edit_points(player_name: str = Form(...), new_points: float = Form(...), reason: str = Form(...)):
    """Edit player points manually"""
    if edit_player_points(player_name, new_points, reason):
        return RedirectResponse(url=f"/admin/{ADMIN_SECRET_PATH}", status_code=303)
    raise HTTPException(500, "Failed to update points")

@app.post(f"/admin/{ADMIN_SECRET_PATH}/reset")
async def admin_reset_all():
    """Reset all player points"""
    if reset_all_points():
        return {"success": True, "message": "All points reset successfully"}
    raise HTTPException(500, "Failed to reset points")

if __name__ == "__main__":
    import uvicorn
    uvicorn.run(app, host="0.0.0.0", port=8000)

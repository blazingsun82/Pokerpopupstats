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

# Templates and static files="
templates = Jinja2Templates(directory=".")
# Only mount static files if directory exists
if Path("static").exists():
    app.mount("/static", StaticFiles(directory="static"), name="static")

# Configuration - change this secret path!
SECRET_UPLOAD_PATH = os.getenv("UPLOAD_SECRET", "bingo-poker-secret-2025")
ADMIN_SECRET_PATH = os.getenv("ADMIN_SECRET", "admin-control-2025")
DATABASE_URL = os.getenv("DATABASE_URL")

# Debug: Print the upload path
print(f"Upload path configured as: /upload/{SECRET_UPLOAD_PATH}")
print(f"Admin path configured as: /admin/{ADMIN_SECRET_PATH}")

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
        
        # Create player_points table with wins and knockouts
        cur.execute('''
            CREATE TABLE IF NOT EXISTS player_points (
                player_name VARCHAR(100) PRIMARY KEY,
                total_points DECIMAL(10,2) DEFAULT 0,
                avatar VARCHAR(50) DEFAULT '',
                tournaments_played INTEGER DEFAULT 0,
                wins INTEGER DEFAULT 0,
                knockouts INTEGER DEFAULT 0,
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
        
        # Create tournament_results table for persistent awards storage
        cur.execute('''
            CREATE TABLE IF NOT EXISTS tournament_results (
                id SERIAL PRIMARY KEY,
                tournament_date VARCHAR(100),
                tournament_id VARCHAR(50),
                total_players INTEGER,
                awards JSONB,
                preparation_h_club JSONB,
                last_updated TIMESTAMP DEFAULT CURRENT_TIMESTAMP
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
            SELECT player_name, total_points, avatar, tournaments_played, wins, knockouts
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

def update_player_points(player_name: str, points: float, wins: int, kos: int, tournament_date: str):
    """Add points, wins, and KOs to player's total"""
    try:
        conn = get_db_connection()
        cur = conn.cursor()
        
        # Upsert player points
        cur.execute('''
            INSERT INTO player_points (player_name, total_points, wins, knockouts, tournaments_played)
            VALUES (%s, %s, %s, %s, 1)
            ON CONFLICT (player_name) 
            DO UPDATE SET 
                total_points = player_points.total_points + %s,
                wins = player_points.wins + %s,
                knockouts = player_points.knockouts + %s,
                tournaments_played = player_points.tournaments_played + 1,
                last_updated = CURRENT_TIMESTAMP
        ''', (player_name, points, wins, kos, points, wins, kos))
        
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
        cur.execute('UPDATE player_points SET total_points = 0, wins = 0, knockouts = 0, tournaments_played = 0')
        
        conn.commit()
        cur.close()
        conn.close()
        return True
    except Exception as e:
        print(f"Error resetting points: {e}")
        return False

def save_tournament_results(data):
    """Save tournament results to PostgreSQL"""
    try:
        conn = get_db_connection()
        cur = conn.cursor()
        
        # Delete old result (keep only latest)
        cur.execute('DELETE FROM tournament_results')
        
        # Insert new result
        cur.execute('''
            INSERT INTO tournament_results (tournament_date, tournament_id, total_players, awards, preparation_h_club)
            VALUES (%s, %s, %s, %s, %s)
        ''', (
            data.get("tournament_date"),
            data.get("tournament_id"),
            data.get("total_players"),
            json.dumps(data.get("awards", {})),
            json.dumps(data.get("preparation_h_club", []))
        ))
        
        conn.commit()
        cur.close()
        conn.close()
        print("Tournament results saved to PostgreSQL")
        return True
    except Exception as e:
        print(f"Error saving tournament results: {e}")
        return False

def load_tournament_results():
    """Load tournament results from PostgreSQL"""
    try:
        conn = get_db_connection()
        cur = conn.cursor(cursor_factory=RealDictCursor)
        
        cur.execute('''
            SELECT tournament_date, tournament_id, total_players, awards, preparation_h_club, last_updated
            FROM tournament_results
            ORDER BY last_updated DESC
            LIMIT 1
        ''')
        
        result = cur.fetchone()
        cur.close()
        conn.close()
        
        if result:
            return {
                "tournament_date": result["tournament_date"],
                "tournament_id": result["tournament_id"],
                "total_players": result["total_players"],
                "awards": result["awards"],  # Already parsed from JSONB
                "preparation_h_club": result["preparation_h_club"],  # Already parsed from JSONB
                "last_updated": result["last_updated"].isoformat()
            }
        
        return None
    except Exception as e:
        print(f"Error loading tournament results: {e}")
        return None

# Initialize database on startup
if DATABASE_URL:
    init_database()
else:
    print("WARNING: DATABASE_URL not set - database features disabled")

# Awards calculation logic (FIXED VERSION)
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
                    'bad_beats': [],
                    'suckouts': []
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
        """Analyze showdown hands to detect genuine bad beats - when strong made hands lose"""
        try:
            if '*** SHOW DOWN ***' not in hand_text:
                return
                
            # Extract showdown section
            showdown_section = hand_text.split('*** SHOW DOWN ***')[1]
            
            # Find all players who showed hands
            showdown_pattern = r'(\w+(?:\*\d+)?): shows \[([^\]]+)\] \(([^)]+)\)'
            showdown_matches = re.findall(showdown_pattern, showdown_section)
            
            # Find who won the pot (IMPORTANT: Check for split pots)
            winner_pattern = r'(\w+(?:\*\d+)?) collected (\d+) from pot'
            winner_matches = re.findall(winner_pattern, hand_text)
            
            # If multiple winners, it's a split pot - NO BAD BEAT POSSIBLE
            if len(winner_matches) > 1:
                print(f"DEBUG: Split pot detected - no bad beat possible")
                return
            
            # Single winner required for bad beat
            winner = winner_matches[0][0] if winner_matches else None
            
            # Check for explicit split pot language
            if any(phrase in hand_text.lower() for phrase in ['split pot', 'divided', 'tied']):
                print(f"DEBUG: Split pot language detected - no bad beat")
                return
            
            print(f"DEBUG: Single winner showdown - {len(showdown_matches)} players showed hands, winner: {winner}")
            
            # Only analyze hands where players showed AND there's a clear single winner
            if len(showdown_matches) >= 2 and winner and len(winner_matches) == 1:
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
                        print(f"DEBUG: {player} showed {cards} ({hand_desc}) - strength: {made_hand_strength}")
                    except Exception as e:
                        print(f"DEBUG: Error processing player {player}: {e}")
                        continue
                
                # Find strong hands that LOST (not tied)
                losing_hands = [h for h in player_hands if not h['won']]
                winning_hand = next((h for h in player_hands if h['won']), None)
                
                if losing_hands and winning_hand:
                    # Check for genuine bad beats - strong made hands losing to stronger ones
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
        """Evaluate the strength of a made hand"""
        hand_desc = hand_description.lower()
        
        if 'royal flush' in hand_desc:
            return 1000
        elif 'straight flush' in hand_desc:
            return 900
        elif 'four of a kind' in hand_desc:
            return 800
        elif 'full house' in hand_desc:
            return 700
        elif 'flush' in hand_desc and 'straight' not in hand_desc:
            return 600
        elif 'straight' in hand_desc and 'flush' not in hand_desc:
            return 500
        elif 'three of a kind' in hand_desc:
            return 400
        elif 'two pair' in hand_desc:
            if any(card in hand_desc for card in ['aces', 'kings', 'queens']):
                return 300
            else:
                return 200
        elif 'pair of' in hand_desc:
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
        else:
            return 50
    
    def _is_genuine_bad_beat(self, losing_hand: Dict, winning_hand: Dict) -> bool:
        """Determine if this qualifies as a genuine bad beat"""
        loser_strength = losing_hand['made_hand_strength']
        winner_strength = winning_hand['made_hand_strength']
        
        if loser_strength >= 400:  # Three of a kind or better
            return True
        
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
        else:
            return 'high card'
    
    def _is_likely_runner_runner(self, description: str, suckout_info: Dict) -> bool:
        """Determine if this was likely a runner-runner win"""
        winning_hand = suckout_info.get('winning_hand', '').lower()
        victim_hand = suckout_info.get('victim_hand', '').lower()
        
        if ('flush' in winning_hand and ('pair' in victim_hand or 'two pair' in victim_hand)):
            return True
        elif ('straight' in winning_hand and ('pair' in victim_hand or 'two pair' in victim_hand)):
            return True
            
        return False
    
    def _determine_final_positions(self, players: Dict, full_text: str):
        """Determine final tournament positions - Top 3 only (FIXED VERSION)"""
        # Initialize all positions as None first
        for name in players:
            if name != 'tournament_info':
                players[name]['final_position'] = None
        
        # Find the final hand (last one in the file)
        hands = re.findall(r'(PokerStars Hand #\d+: Tournament #\d+.*?)(?=PokerStars Hand #\d+: Tournament #\d+|\Z)', full_text, re.DOTALL)
        
        if hands:
            final_hand = hands[-1]
            
            # Find who won the final pot (1st place)
            winner_pattern = r'(\w+(?:\*\d+)?) collected \d+ from pot'
            final_winner_match = re.search(winner_pattern, final_hand)
            
            # Find who showed cards in the final hand (both finalists)
            showdown_pattern = r'(\w+(?:\*\d+)?): shows'
            finalists = re.findall(showdown_pattern, final_hand)
            
            if final_winner_match and finalists:
                winner = final_winner_match.group(1)
                # Winner is 1st
                if winner in players:
                    players[winner]['final_position'] = 1
                
                # Other finalist is 2nd
                for finalist in finalists:
                    if finalist != winner and finalist in players:
                        players[finalist]['final_position'] = 2
                        break
        
        # Assign 3rd place based on highest chip count among remaining players
        unassigned = [(name, data) for name, data in players.items() 
                     if name != 'tournament_info' and data.get('final_position') is None]
        
        if unassigned:
            # Sort by max chips and assign 3rd place to the top player
            unassigned.sort(key=lambda x: x[1].get('max_chips', 0), reverse=True)
            if unassigned:  # Double check we have players
                third_place_player = unassigned[0]
                players[third_place_player[0]]['final_position'] = 3

        # Everyone else stays None (no specific position tracked)
    
    def _calculate_awards(self, players_data: Dict[str, Dict]) -> Dict[str, Dict]:
        """Calculate fun club-style awards from parsed player data (SAFER VERSION)"""
        players = {k: v for k, v in players_data.items() if k != 'tournament_info'}
        
        if not players:
            return self._get_sample_awards()
        
        awards = {}
        awarded_players = set()  # Track who has won BEHAVIORAL awards (not placement awards)
        
        # PLACEMENT AWARDS - EXEMPT from one-award restriction
        
        # Tournament Champion (1st place)
        champion_candidates = [(name, data) for name, data in players.items() 
                              if data.get('final_position') == 1]
        if champion_candidates:
            champion = champion_candidates[0]
            awards["🏆 Tournament Champion"] = {
                "winner": champion[0],
                "description": "Survived the chaos and claimed the crown",
                "stat": f"Outlasted {len(players)-1} other players"
            }
        
        # Runner Up (2nd place)
        runner_up_candidates = [(name, data) for name, data in players.items() 
                               if data.get('final_position') == 2]
        if runner_up_candidates:
            second_place = runner_up_candidates[0]
            awards["🥈 Runner Up"] = {
                "winner": second_place[0],
                "description": "So close to glory, yet so far",
                "stat": "Heads-up warrior"
            }
        
        # BEHAVIORAL AWARDS - Subject to one-award restriction
        
        # Most Aggressive
        aggressive_players = [(name, data) for name, data in players.items() 
                            if data.get('hands_played', 0) > 5 and name not in awarded_players]
        if aggressive_players:
            # Safe calculation with default values
            best_aggressive = None
            best_aggro_ratio = 0
            for name, data in aggressive_players:
                hands_played = max(data.get('hands_played', 1), 1)
                aggressive_actions = data.get('aggressive_actions', 0)
                ratio = aggressive_actions / hands_played
                if ratio > best_aggro_ratio:
                    best_aggro_ratio = ratio
                    best_aggressive = (name, data)
            
            if best_aggressive:
                awards["🔥 Most Aggressive"] = {
                    "winner": best_aggressive[0],
                    "description": "Fearless bets and raises kept everyone on edge",
                    "stat": "Never met a pot they didn't want to steal"
                }
                awarded_players.add(best_aggressive[0])
        
        # Calling Station
        calling_candidates = [(name, data) for name, data in players.items()
                             if name not in awarded_players and data.get('hands_played', 0) > 5]
        if calling_candidates:
            # Safe calculation
            best_caller = None
            best_call_ratio = 0
            for name, data in calling_candidates:
                hands_played = max(data.get('hands_played', 1), 1)
                calls = data.get('calls', 0)
                ratio = calls / hands_played
                if ratio > best_call_ratio:
                    best_call_ratio = ratio
                    best_caller = (name, data)
            
            if best_caller:
                awards["📞 Calling Station"] = {
                    "winner": best_caller[0],
                    "description": "Never saw a bet they didn't want to call",
                    "stat": "The human slot machine"
                }
                awarded_players.add(best_caller[0])
        
        # Tightest Player
        tight_candidates = [(name, data) for name, data in players.items()
                           if name not in awarded_players and data.get('hands_played', 0) > 5]
        if tight_candidates:
            # Safe calculation
            tightest_player = None
            lowest_vpip = 1.0
            for name, data in tight_candidates:
                hands_played = max(data.get('hands_played', 1), 1)
                hands_voluntary = data.get('hands_voluntarily_played', 0)
                vpip = hands_voluntary / hands_played
                if vpip < lowest_vpip:
                    lowest_vpip = vpip
                    tightest_player = (name, data)
            
            if tightest_player:
                awards["🧊 Tightest Player"] = {
                    "winner": tightest_player[0],
                    "description": "Plays only a small, selective number of hands",
                    "stat": "Classic tight-aggressive strategy"
                }
                awarded_players.add(tightest_player[0])
        
        # YOLO Award - Look for suckouts
        yolo_candidates = []
        for name, data in players.items():
            if name in awarded_players:
                continue
            suckouts = data.get('suckouts', [])
            if suckouts:
                yolo_candidates.append((name, suckouts[0]))
        
        if yolo_candidates:
            awards["🎲 YOLO Award"] = {
                "winner": yolo_candidates[0][0],
                "description": "Biggest pot won with questionable starting hand",
                "stat": "Sometimes you gotta risk it all"
            }
            awarded_players.add(yolo_candidates[0][0])
        
        # Hollywood Actor (Most bets without many showdowns)
        bluffer_candidates = [(name, data) for name, data in players.items() 
                            if name not in awarded_players and data.get('bets', 0) > 2]
        if bluffer_candidates:
            # Safe calculation
            best_bluffer = None
            best_bluff_ratio = 0
            for name, data in bluffer_candidates:
                bets = data.get('bets', 0)
                showdowns = max(data.get('showdowns', 1), 1)
                ratio = bets / showdowns
                if ratio > best_bluff_ratio:
                    best_bluff_ratio = ratio
                    best_bluffer = (name, data)
            
            if best_bluffer:
                awards["🎭 Hollywood Actor"] = {
                    "winner": best_bluffer[0],
                    "description": "Most bluffs attempted (successful or failed)",
                    "stat": "Master of deception and theatrics"
                }
                awarded_players.add(best_bluffer[0])
        
        # Bubble Boy (placement award - EXEMPT from one-award restriction)
        if len(players) >= 4:
            bubble_position = (len(players) + 1) // 2
            bubble_candidates = [p for p in players.items() 
                               if p[1].get('final_position') == bubble_position]
            if bubble_candidates:
                awards["💀 Bubble Boy"] = {
                    "winner": bubble_candidates[0][0],
                    "description": "Knocked out just before the money",
                    "stat": "So close to cashing, yet so far"
                }
        
        return awards
    
    def _get_sample_awards(self):
        """Return sample awards when no real data"""
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
            "📞 Calling Station": {
                "winner": "Player3", 
                "description": "Never saw a bet they didn't want to call", 
                "stat": "The human slot machine"
            }
        }
    
    def _generate_sample_data(self):
        """Fallback sample data"""
        return {
            "tournament_date": datetime.now().strftime("%B %d, %Y at %I:%M %p"),
            "tournament_id": "3928736979",
            "total_players": 6,
            "awards": self._get_sample_awards(),
            "preparation_h_club": [],
            "last_updated": datetime.now().isoformat()
        }

parser = PokerAwardsParser()

# Load existing results from PostgreSQL
def load_results():
    """Load tournament results from PostgreSQL, fallback to sample data"""
    # Try loading from PostgreSQL first
    result = load_tournament_results()
    if result:
        print("Loaded tournament results from PostgreSQL")
        return result
    
    # Fallback to sample data
    print("No tournament results found, using sample data")
    return parser._generate_sample_data()

def save_results(data):
    """Save tournament results to PostgreSQL"""
    if save_tournament_results(data):
        print("Tournament results saved to PostgreSQL successfully")
    else:
        print("Failed to save tournament results to PostgreSQL")

# Routes
@app.get("/", response_class=HTMLResponse)
async def public_board(request: Request):
    """Public awards board"""
    results = load_results()
    return templates.TemplateResponse("index.html", {
        "request": request,
        "results": results,
        "is_public": True
    })

@app.get(f"/upload/{SECRET_UPLOAD_PATH}", response_class=HTMLResponse)
async def upload_page(request: Request):
    """Secret upload page"""
    results = load_results()
    return templates.TemplateResponse("upload.html", {
        "request": request,
        "results": results,
        "upload_url": f"/upload/{SECRET_UPLOAD_PATH}/process",
        "admin_path": ADMIN_SECRET_PATH
    })

@app.post(f"/upload/{SECRET_UPLOAD_PATH}/process")
async def process_upload(file: UploadFile = File(...)):
    """Process the uploaded TXT file"""
    print(f"Received file upload: {file.filename}")
    
    if not file.filename.endswith('.txt'):
        raise HTTPException(400, "Please upload a TXT file")
    
    try:
        content = await file.read()
        print(f"Read {len(content)} bytes from uploaded file")
        
        results = parser.parse_txt(content)
        
        # Save to PostgreSQL instead of files
        save_results(results)
        await sse_manager.broadcast_update(results)
        
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
        current_data = load_results()
        yield {"event": "init", "data": json.dumps(current_data)}
        
        queue = asyncio.Queue()
        
        async def sender(event_data):
            await queue.put(event_data)
        
        sse_manager.add_connection(sender)
        
        try:
            while True:
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
async def upload_points(file: UploadFile = File(...)):
    """Process uploaded points file with wins and KOs"""
    if not file.filename.endswith('.txt'):
        raise HTTPException(400, "Please upload a TXT file")
    
    try:
        content = await file.read()
        text = content.decode('utf-8')
        
        tournament_date = datetime.now().strftime("%Y-%m-%d")
        
        lines = text.strip().split('\n')
        updated_count = 0
        errors = []
        
        for line_num, line in enumerate(lines, 1):
            line = line.strip()
            if not line:
                continue
            
            # Parse format: "PlayerName: Points, Wins, KO"
            if ':' in line:
                parts = line.split(':', 1)
                player_name = parts[0].strip()
                values = parts[1].strip().split(',')
                
                try:
                    points = float(values[0].strip())
                    wins = int(values[1].strip()) if len(values) > 1 else 0
                    kos = int(values[2].strip()) if len(values) > 2 else 0
                    
                    if update_player_points(player_name, points, wins, kos, tournament_date):
                        updated_count += 1
                except (ValueError, IndexError) as e:
                    errors.append(f"Line {line_num}: Invalid format - {str(e)}")
            else:
                errors.append(f"Line {line_num}: Missing colon separator")
        
        message = f"Updated {updated_count} players"
        if errors:
            message += f". Errors: {'; '.join(errors[:3])}"
        
        return {
            "success": True,
            "message": message,
            "players_updated": updated_count,
            "errors": errors if errors else None
        }
    
    except Exception as e:
        raise HTTPException(500, f"Error processing points file: {str(e)}")

@app.get(f"/admin/{ADMIN_SECRET_PATH}", response_class=HTMLResponse)
async def admin_panel(request: Request):
    """Admin control panel"""
    players = get_all_player_points()
    return templates.TemplateResponse("admin.html", {
        "request": request,
        "players": players,
        "admin_path": ADMIN_SECRET_PATH,
        "upload_path": SECRET_UPLOAD_PATH
    })

@app.post(f"/admin/{ADMIN_SECRET_PATH}/edit")
async def admin_edit_points(
    player_name: str = Form(...), 
    points: float = Form(...), 
    wins: int = Form(...), 
    knockouts: int = Form(...)
):
    """Edit player points, wins, and KOs manually"""
    try:
        conn = get_db_connection()
        cur = conn.cursor()
        
        # Add points, wins, and KOs to player's existing totals
        cur.execute('''
            INSERT INTO player_points (player_name, total_points, wins, knockouts)
            VALUES (%s, %s, %s, %s)
            ON CONFLICT (player_name)
            DO UPDATE SET 
                total_points = player_points.total_points + %s,
                wins = player_points.wins + %s,
                knockouts = player_points.knockouts + %s,
                last_updated = CURRENT_TIMESTAMP
        ''', (player_name, points, wins, knockouts, points, wins, knockouts))
        
        # Record in history
        cur.execute('''
            INSERT INTO points_history (player_name, tournament_date, points_change, action_type)
            VALUES (%s, %s, %s, 'manual_edit')
        ''', (player_name, 'Manual Edit', points))
        
        conn.commit()
        cur.close()
        conn.close()
        
        return RedirectResponse(url=f"/admin/{ADMIN_SECRET_PATH}", status_code=303)
    except Exception as e:
        raise HTTPException(500, f"Failed to update points: {str(e)}")

@app.post(f"/admin/{ADMIN_SECRET_PATH}/update-avatar")
async def admin_update_avatar(player_name: str = Form(...), avatar: str = Form(...)):
    """Update player avatar"""
    try:
        conn = get_db_connection()
        cur = conn.cursor()
        
        cur.execute('''
            INSERT INTO player_points (player_name, avatar)
            VALUES (%s, %s)
            ON CONFLICT (player_name)
            DO UPDATE SET avatar = %s, last_updated = CURRENT_TIMESTAMP
        ''', (player_name, avatar, avatar))
        
        conn.commit()
        cur.close()
        conn.close()
        
        return RedirectResponse(url=f"/admin/{ADMIN_SECRET_PATH}", status_code=303)
    except Exception as e:
        raise HTTPException(500, f"Failed to update avatar: {str(e)}")

@app.post(f"/admin/{ADMIN_SECRET_PATH}/reset")
async def admin_reset_all():
    """Reset all player points"""
    if reset_all_points():
        return RedirectResponse(url=f"/admin/{ADMIN_SECRET_PATH}", status_code=303)
    raise HTTPException(500, "Failed to reset points")

@app.get(f"/admin/{ADMIN_SECRET_PATH}/schema-sync")
async def schema_sync():
    """Synchronize database schema with application code"""
    try:
        conn = get_db_connection()
        cur = conn.cursor()
        
        # Drop existing tables
        cur.execute('DROP TABLE IF EXISTS points_history CASCADE')
        cur.execute('DROP TABLE IF EXISTS player_points CASCADE')
        cur.execute('DROP TABLE IF EXISTS tournament_results CASCADE')
        
        conn.commit()
        cur.close()
        conn.close()
        
        # Recreate with correct schema
        init_database()
        
        return JSONResponse(content={
            "success": True, 
            "message": "Database schema synchronized successfully"
        })
    except Exception as e:
        return JSONResponse(content={"success": False, "error": str(e)})

if __name__ == "__main__":
    import uvicorn
    uvicorn.run(app, host="0.0.0.0", port=8000)

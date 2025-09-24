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

# Debug: Print the upload path
print(f"Upload path configured as: /upload/{SECRET_UPLOAD_PATH}")

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
        else:
            return 'high card'
    
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

if __name__ == "__main__":
    import uvicorn
    uvicorn.run(app, host="0.0.0.0", port=8000)

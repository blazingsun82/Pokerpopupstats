calculateAwards(playersData) {
    const players = Object.fromEntries(
      Object.entries(playersData).filter(([k]) => k !== 'tournament_info')
    );
    
    if (Object.keys(players).length === 0) {
      return {};
    }
    
    const awards = {};
    const awardedPlayers = new Set();
    
    // PLACEMENT AWARDS
    
    // Tournament Champion (1st place)
    const championCandidates = Object.entries(players).filter(([, data]) => data.final_position === 1);
    if (championCandidates.length > 0) {
      const [championName] = championCandidates[0];
      awards['🏆 Tournament Champion'] = {
        winner: championName,
        description: 'Survived the chaos and claimed the crown',
        stat: `Outlasted ${Object.keys(players).length - 1} other players`
      };
    }
    
    // Runner Up (2nd place)
    const runnerUpCandidates = Object.entries(players).filter(([, data]) => data.final_position === 2);
    if (runnerUpCandidates.length > 0) {
      const [runnerUpName] = runnerUpCandidates[0];
      awards['🥈 Runner Up'] = {
        winner: runnerUpName,
        description: 'So close to glory, yet so far',
        stat: 'Heads-up warrior'
      };
    }
    
    // BEHAVIORAL AWARDS
    
    // Most Aggressive
    const aggressivePlayers = Object.entries(players).filter(([name, data]) => 
      (data.hands_played || 0) > 5 && !awardedPlayers.has(name)
    );
    
    if (aggressivePlayers.length > 0) {
      let bestAggressive = null;
      let bestAggroRatio = 0;
      
      aggressivePlayers.forEach(([name, data]) => {
        const handsPlayed = Math.max(data.hands_played || 1, 1);
        const aggressiveActions = data.aggressive_actions || 0;
        const ratio = aggressiveActions / handsPlayed;
        
        if (ratio > bestAggroRatio) {
          bestAggroRatio = ratio;
          bestAggressive = name;
        }
      });
      
      if (bestAggressive) {
        awards['🔥 Most Aggressive'] = {
          winner: bestAggressive,
          description: 'Fearless bets and raises kept everyone on edge',
          stat: 'Never met a pot they didn\'t want to steal'
        };
        awardedPlayers.add(bestAggressive);
      }
    }
    
    // Calling Station
    const callingCandidates = Object.entries(players).filter(([name, data]) => 
      !awardedPlayers.has(name) && (data.hands_played || 0) > 5
    );
    
    if (callingCandidates.length > 0) {
      let bestCaller = null;
      let bestCallRatio = 0;
      
      callingCandidates.forEach(([name, data]) => {
        const handsPlayed = Math.max(data.hands_played || 1, 1);
        const calls = data.calls || 0;
        const ratio = calls / handsPlayed;
        
        if (ratio > bestCallRatio) {
          bestCallRatio = ratio;
          bestCaller = name;
        }
      });
      
      if (bestCaller) {
        awards['📞 Calling Station'] = {
          winner: bestCaller,
          description: 'Never saw a bet they didn\'t want to call',
          stat: 'The human slot machine'
        };
        awardedPlayers.add(bestCaller);
      }
    }
    
    // Tightest Player
    const tightCandidates = Object.entries(players).filter(([name, data]) => 
      !awardedPlayers.has(name) && (data.hands_played || 0) > 5
    );
    
    if (tightCandidates.length > 0) {
      let tightestPlayer = null;
      let lowestVpip = 1.0;
      
      tightCandidates.forEach(([name, data]) => {
        const handsPlayed = Math.max(data.hands_played || 1, 1);
        const handsVoluntary = data.hands_voluntarily_played || 0;
        const vpip = handsVoluntary / handsPlayed;
        
        if (vpip < lowestVpip) {
          lowestVpip = vpip;
          tightestPlayer = name;
        }
      });
      
      if (tightestPlayer) {
        awards['🧊 Tightest Player'] = {
          winner: tightestPlayer,
          description: 'Plays only a small, selective number of hands',
          stat: 'Classic tight-aggressive strategy'
        };
        awardedPlayers.add(tightestPlayer);
      }
    }
    
    // Comeback Kid - Largest comeback from smallest chip stack
    const comebackCandidates = [];
    const allChips = Object.values(players).map(data => data.max_chips || 0).filter(chips => chips > 0);
    if (allChips.length > 0) {
      const minChips = Math.min(...allChips);
      
      Object.entries(players).forEach(([name, data]) => {
        if (awardedPlayers.has(name)) return;
        
        const finalPos = data.final_position;
        const maxChips = data.max_chips || 0;
        
        if (finalPos !== null && maxChips <= minChips * 2 && finalPos <= Object.keys(players).length / 2) {
          const comebackScore = (Object.keys(players).length - finalPos) / Math.max(maxChips, 1);
          comebackCandidates.push([name, comebackScore]);
        }
      });
    }
    
    if (comebackCandidates.length > 0) {
      comebackCandidates.sort((a, b) => b[1] - a[1]);
      const comebackKing = comebackCandidates[0][0];
      
      awards['🎯 Comeback Kid'] = {
        winner: comebackKing,
        description: 'Largest comeback from the smallest chip stack',
        stat: 'Rose from the ashes like a phoenix'
      };
      awardedPlayers.add(comebackKing);
    }
    
    // YOLO Award - Biggest pot won with questionable starting hand
    const yoloCandidates = [];
    Object.entries(players).forEach(([name, data]) => {
      if (awardedPlayers.has(name)) return;
      
      const suckouts = data.suckouts || [];
      suckouts.forEach(suckout => {
        const description = (suckout.description || '').toLowerCase();
        if (['7', '2', 'offsuit', 'unsuited'].some(badHand => description.includes(badHand))) {
          yoloCandidates.push([name, suckout]);
        }
      });
    });
    
    if (yoloCandidates.length > 0) {
      const yoloWinner = yoloCandidates[0][0];
      awards['🎲 YOLO Award'] = {
        winner: yoloWinner,
        description: 'Biggest pot won with the worst starting hand',
        stat: 'Sometimes you gotta risk it all'
      };
      awardedPlayers.add(yoloWinner);
    }
    
    // Doggy Paddling Award - Survives longer than expected
    const survivors = Object.entries(players).filter(([name, data]) => 
      !awardedPlayers.has(name) && (data.final_position || 999) > Object.keys(players).length * 0.6
    );
    
    if (survivors.length > 0) {
      let longestSurvivor = null;
      let mostHands = 0;
      
      survivors.forEach(([name, data]) => {
        const handsPlayed = data.hands_played || 0;
        if (handsPlayed > mostHands) {
          mostHands = handsPlayed;
          longestSurvivor = name;
        }
      });
      
      if (longestSurvivor) {
        awards['🐶💦 Doggy Paddling Award'] = {
          winner: longestSurvivor,
          description: 'Consistently hovers at the bottom but somehow stays alive longer than expected',
          stat: 'Survival instincts kicked in'
        };
        awardedPlayers.add(longestSurvivor);
      }
    }
    
    // Hollywood Actor (Most bets without many showdowns)
    const blufferCandidates = Object.entries(players).filter(([name, data]) => 
      !awardedPlayers.has(name) && (data.bets || 0) > 2
    );
    
    if (blufferCandidates.length > 0) {
      let bestBluffer = null;
      let bestBluffRatio = 0;
      
      blufferCandidates.forEach(([name, data]) => {
        const bets = data.bets || 0;
        const showdowns = Math.max(data.showdowns || 1, 1);
        const ratio = bets / showdowns;
        
        if (ratio > bestBluffRatio) {
          bestBluffRatio = ratio;
          bestBluffer = name;
        }
      });
      
      if (bestBluffer) {
        awards['🎭 Hollywood Actor'] = {
          winner: bestBluffer,
          description: 'Most bluffs attempted (successful or failed)',
          stat: 'Master of deception and theatrics'
        };
        awardedPlayers.add(bestBluffer);
      }
    }
    
    // 7-2 Hero - Won with worst possible hand
    const badHandWinners = [];
    Object.entries(players).forEach(([name, data]) => {
      if (awardedPlayers.has(name)) return;
      
      const suckouts = data.suckouts || [];
      suckouts.forEach(suckout => {
        const winningHand = (suckout.winning_hand || '').toLowerCase();
        if ((winningHand.includes('7') && winningHand.includes('2')) || winningHand.includes('worst')) {
          badHandWinners.push([name, suckout]);
        }
      });
    });
    
    if (badHandWinners.length > 0) {
      const heroWinner = badHandWinners[0][0];
      awards['💩 7-2 Hero'] = {
        winner: heroWinner,
        description: 'Won with the infamous 7-2 offsuit',
        stat: 'Turned trash into treasure'
      };
      awardedPlayers.add(heroWinner);
    }
    
    // Donkey (poor decision making)
    const donkeyCandidates = [];
    Object.entries(players).forEach(([name, data]) => {
      if (awardedPlayers.has(name)) return;
      
      const handsPlayed = data.hands_played || 0;
      if (handsPlayed > 10) {
        const vpip = (data.hands_voluntarily_played || 0) / handsPlayed;
        const winRate = (data.showdown_wins || 0) / Math.max(data.showdowns || 1, 1);
        
        if (vpip > 0.4 && winRate < 0.3) {
          const donkeyScore = vpip / (winRate + 0.1);
          donkeyCandidates.push([name, donkeyScore, vpip]);
        }
      }
    });
    
    if (donkeyCandidates.length > 0) {
    if (donkeyCandidates.length > 0) {
      donkeyCandidates.sort((a, b) => b[1] - a[1]);
      const worstPlayer = donkeyCandidates[0];
      
      if (worstPlayer[1] > 1.5) {
        awards['🐴 Donkey'] = {
          winner: worstPlayer[0],
          description: 'Made questionable decisions and played too many weak hands',
          stat: `Played ${Math.round(worstPlayer[2] * 100)}% of hands with poor results`
        };
        awardedPlayers.add(worstPlayer[0]);
      }
    }
    
    // ABC Player
    const abcCandidates = Object.entries(players).filter(([name, data]) => {
      if (awardedPlayers.has(name) || (data.hands_played || 0) <= 5) return false;
      
      const aggroRatio = (data.aggressive_actions || 0) / (data.hands_played || 1);
      return aggroRatio > 0.15 && aggroRatio < 0.35;
    });
    
    if (abcCandidates.length > 0) {
      let bestAbc = null;
      let mostShowdownWins = 0;
      
      abcCandidates.forEach(([name, data]) => {
        const showdownWins = data.showdown_wins || 0;
        if (showdownWins > mostShowdownWins) {
          mostShowdownWins = showdownWins;
          bestAbc = name;
        }
      });
      
      if (bestAbc) {
        awards['📚 ABC Player'] = {
          winner: bestAbc,
          description: 'Played textbook poker, predictable as clockwork',
          stat: 'By-the-book basic strategy'
        };
        awardedPlayers.add(bestAbc);
      }
    }
    
    // Bubble Boy (placement award - EXEMPT from one-award restriction)
    if (Object.keys(players).length >= 4) {
      const bubblePosition = Math.floor((Object.keys(players).length + 1) / 2);
      const bubbleCandidates = Object.entries(players).filter(([, data]) => 
        data.final_position === bubblePosition
      );
      
      if (bubbleCandidates.length > 0) {
        awards['💀 Bubble Boy'] = {
          winner: bubbleCandidates[0][0],
          description: 'Knocked out just before the money in heartbreaking fashion',
          stat: 'So close to cashing, yet so far'
        };
      }
    }
    
    return awards;
  }
}

function generateEmptyTournamentData() {
  return {
    tournament_date: new Date().toLocaleDateString('en-US', { 
      year: 'numeric', month: 'long', day: 'numeric', 
      hour: 'numeric', minute: '2-digit' 
    }),
    tournament_id: 'No tournaments yet',
    total_players: 0,
    awards: {},
    preparation_h_club: [],
    last_updated: new Date().toISOString()
  };
}// Cloudflare Functions - Tournament Processor
// Replaces the Python main.py with JavaScript for Cloudflare

export default {
  async fetch(request, env, ctx) {
    const url = new URL(request.url);
    const path = url.pathname;

    // CORS headers for all responses
    const corsHeaders = {
      'Access-Control-Allow-Origin': '*',
      'Access-Control-Allow-Methods': 'GET, POST, OPTIONS',
      'Access-Control-Allow-Headers': 'Content-Type',
    };

    // Handle CORS preflight
    if (request.method === 'OPTIONS') {
      return new Response(null, { headers: corsHeaders });
    }

    try {
      // Route handling
      if (path === '/' && request.method === 'GET') {
        return await handleMainPage(env, corsHeaders);
      } else if (path === '/upload/bingo-poker-secret-2025/process' && request.method === 'POST') {
        return await handleTournamentUpload(request, env, corsHeaders);
      } else if (path === '/api/tournament-data' && request.method === 'GET') {
        return await handleApiData(env, corsHeaders);
      } else if (path === '/leaderboard' && request.method === 'GET') {
        return await handleLeaderboard(env, corsHeaders);
      }

      return new Response('Not Found', { status: 404, headers: corsHeaders });
    } catch (error) {
      console.error('Function error:', error);
      return new Response(JSON.stringify({ error: error.message }), {
        status: 500,
        headers: { ...corsHeaders, 'Content-Type': 'application/json' }
      });
    }
  }
};

// Database initialization
async function initDatabase(env) {
  try {
    // Create tournament_results table
    await env.DB.prepare(`
      CREATE TABLE IF NOT EXISTS tournament_results (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        tournament_date TEXT,
        tournament_id TEXT,
        total_players INTEGER,
        awards TEXT,
        preparation_h_club TEXT,
        last_updated DATETIME DEFAULT CURRENT_TIMESTAMP
      )
    `).run();

    // Create player_points table
    await env.DB.prepare(`
      CREATE TABLE IF NOT EXISTS player_points (
        player_name TEXT PRIMARY KEY,
        total_points REAL DEFAULT 0,
        avatar TEXT DEFAULT '',
        tournaments_played INTEGER DEFAULT 0,
        wins INTEGER DEFAULT 0,
        knockouts INTEGER DEFAULT 0,
        last_updated DATETIME DEFAULT CURRENT_TIMESTAMP
      )
    `).run();

    console.log('Database initialized successfully');
  } catch (error) {
    console.error('Database initialization error:', error);
  }
}

// Main page handler
async function handleMainPage(env, corsHeaders) {
  await initDatabase(env);
  const tournamentData = await loadTournamentResults(env);
  
  return new Response(JSON.stringify(tournamentData), {
    headers: { ...corsHeaders, 'Content-Type': 'application/json' }
  });
}

// API data handler
async function handleApiData(env, corsHeaders) {
  const tournamentData = await loadTournamentResults(env);
  
  return new Response(JSON.stringify(tournamentData), {
    headers: { ...corsHeaders, 'Content-Type': 'application/json' }
  });
}

// Tournament upload handler
async function handleTournamentUpload(request, env, corsHeaders) {
  await initDatabase(env);
  
  try {
    const formData = await request.formData();
    const file = formData.get('file');
    
    if (!file || !file.name.endsWith('.txt')) {
      return new Response(JSON.stringify({ error: 'Please upload a TXT file' }), {
        status: 400,
        headers: { ...corsHeaders, 'Content-Type': 'application/json' }
      });
    }

    const content = await file.text();
    console.log(`Processing file: ${file.name}, size: ${content.length} characters`);
    
    const parser = new PokerAwardsParser();
    const results = parser.parseTxt(content);
    
    // Save to D1 database
    await saveTournamentResults(env, results);
    
    return new Response(JSON.stringify({
      success: true,
      message: 'Awards updated successfully!',
      results: results
    }), {
      headers: { ...corsHeaders, 'Content-Type': 'application/json' }
    });
    
  } catch (error) {
    console.error('Upload processing error:', error);
    return new Response(JSON.stringify({ error: `Error processing file: ${error.message}` }), {
      status: 500,
      headers: { ...corsHeaders, 'Content-Type': 'application/json' }
    });
  }
}

// Leaderboard handler
async function handleLeaderboard(env, corsHeaders) {
  try {
    const result = await env.DB.prepare(`
      SELECT player_name, total_points, avatar, tournaments_played, wins, knockouts
      FROM player_points
      ORDER BY total_points DESC
    `).all();

    return new Response(JSON.stringify(result.results || []), {
      headers: { ...corsHeaders, 'Content-Type': 'application/json' }
    });
  } catch (error) {
    console.error('Leaderboard error:', error);
    return new Response(JSON.stringify([]), {
      headers: { ...corsHeaders, 'Content-Type': 'application/json' }
    });
  }
}

// Database functions
async function saveTournamentResults(env, data) {
  try {
    // Delete old results (keep only latest)
    await env.DB.prepare('DELETE FROM tournament_results').run();
    
    // Insert new result
    await env.DB.prepare(`
      INSERT INTO tournament_results (tournament_date, tournament_id, total_players, awards, preparation_h_club)
      VALUES (?, ?, ?, ?, ?)
    `).bind(
      data.tournament_date,
      data.tournament_id,
      data.total_players,
      JSON.stringify(data.awards),
      JSON.stringify(data.preparation_h_club)
    ).run();
    
    console.log('Tournament results saved to D1');
    return true;
  } catch (error) {
    console.error('Error saving tournament results:', error);
    return false;
  }
}

async function loadTournamentResults(env) {
  try {
    const result = await env.DB.prepare(`
      SELECT tournament_date, tournament_id, total_players, awards, preparation_h_club, last_updated
      FROM tournament_results
      ORDER BY last_updated DESC
      LIMIT 1
    `).first();
    
    if (result) {
      return {
        tournament_date: result.tournament_date,
        tournament_id: result.tournament_id,
        total_players: result.total_players,
        awards: JSON.parse(result.awards),
        preparation_h_club: JSON.parse(result.preparation_h_club),
        last_updated: result.last_updated
      };
    }
    
    return generateSampleData();
  } catch (error) {
    console.error('Error loading tournament results:', error);
    return generateSampleData();
  }
}

function generateSampleData() {
  return {
    tournament_date: new Date().toLocaleDateString('en-US', { 
      year: 'numeric', month: 'long', day: 'numeric', 
      hour: 'numeric', minute: '2-digit' 
    }),
    tournament_id: '3928736979',
    total_players: 6,
    awards: {
      '🏆 Tournament Champion': {
        winner: 'Player1',
        description: 'Survived the chaos and claimed the crown',
        stat: 'Outlasted 5 other players'
      },
      '🔥 Most Aggressive': {
        winner: 'Player2',
        description: 'Fearless bets and raises kept everyone on edge',
        stat: 'Never met a pot they didn\'t want to steal'
      },
      '📞 Calling Station': {
        winner: 'Player3',
        description: 'Never saw a bet they didn\'t want to call',
        stat: 'The human slot machine'
      }
    },
    preparation_h_club: [],
    last_updated: new Date().toISOString()
  };
}

// Poker Awards Parser (converted from Python)
class PokerAwardsParser {
  parseTxt(content) {
    try {
      console.log(`Starting to parse file of size: ${content.length} characters`);
      const playersData = this.extractFromTxt(content);
      const playerCount = Object.keys(playersData).filter(k => k !== 'tournament_info').length;
      console.log(`Extracted data for ${playerCount} players`);
      
      const awards = this.calculateAwards(playersData);
      console.log(`Calculated ${Object.keys(awards).length} awards`);
      
      const tournamentInfo = playersData.tournament_info || {};
      const preparationHClub = this.extractPreparationHClub(playersData);
      
      return {
        tournament_date: tournamentInfo.date || new Date().toLocaleDateString(),
        tournament_id: tournamentInfo.id || 'Unknown',
        total_players: tournamentInfo.player_count || playerCount,
        awards: awards,
        preparation_h_club: preparationHClub,
        last_updated: new Date().toISOString()
      };
    } catch (error) {
      console.error('Error parsing text file:', error);
      return generateSampleData();
    }
  }

  extractFromTxt(text) {
    console.log(`File content length: ${text.length} characters`);
    console.log(`First 200 characters: ${text.substring(0, 200)}`);
    
    const players = {};
    const tournamentInfo = {};
    
    // Extract tournament information
    const tournamentMatch = text.match(/Tournament #(\d+)/);
    if (tournamentMatch) {
      tournamentInfo.id = tournamentMatch[1];
      console.log(`Found tournament ID: ${tournamentInfo.id}`);
    }
    
    const dateMatch = text.match(/(\d{4}\/\d{2}\/\d{2} \d{2}:\d{2}:\d{2})/);
    if (dateMatch) {
      tournamentInfo.date = dateMatch[1];
      console.log(`Found tournament date: ${tournamentInfo.date}`);
    }
    
    // Extract all hands using PokerStars format
    const handRegex = /(PokerStars Hand #\d+: Tournament #\d+.*?)(?=PokerStars Hand #\d+: Tournament #\d+|\s*$)/gs;
    const hands = [...text.matchAll(handRegex)].map(match => match[1]);
    console.log(`Found ${hands.length} hands`);
    
    // Debug: Check how many hands have showdowns
    const showdownCount = hands.filter(hand => hand.includes('*** SHOW DOWN ***')).length;
    console.log(`DEBUG: Found ${showdownCount} hands with showdowns out of ${hands.length} total hands`);
    
    if (hands.length > 0) {
      console.log(`First hand preview: ${hands[0].substring(0, 150)}...`);
    }
    
    hands.forEach((handText, i) => {
      if (i < 3) {
        console.log(`Processing hand ${i + 1}`);
        console.log(`DEBUG: Hand ${i + 1} ${handText.includes('*** SHOW DOWN ***') ? 'contains' : 'has no'} showdown`);
      }
      this.parseHand(handText, players);
    });
    
    // Calculate final positions
    this.determineFinalPositions(players, text);
    
    tournamentInfo.player_count = Object.keys(players).length;
    console.log(`Final player count: ${tournamentInfo.player_count}`);
    
    players.tournament_info = tournamentInfo;
    return players;
  }

  parseHand(handText, players) {
    // Extract players and their chip counts
    const seatRegex = /Seat \d+: (\w+(?:\*\d+)?)\s*\((\d+) in chips\)/g;
    let seatMatch;
    
    while ((seatMatch = seatRegex.exec(handText)) !== null) {
      const [, playerName, chips] = seatMatch;
      
      if (!players[playerName]) {
        players[playerName] = {
          hands_played: 0,
          raises: 0,
          calls: 0,
          folds: 0,
          bets: 0,
          checks: 0,
          showdowns: 0,
          showdown_wins: 0,
          total_won: 0,
          total_bet: 0,
          aggressive_actions: 0,
          passive_actions: 0,
          hands_voluntarily_played: 0,
          final_position: null,
          max_chips: parseInt(chips),
          bad_beats: [],
          suckouts: []
        };
      }
      
      players[playerName].hands_played += 1;
      players[playerName].max_chips = Math.max(players[playerName].max_chips, parseInt(chips));
    }
    
    // Analyze showdowns for bad beats
    if (handText.includes('*** SHOW DOWN ***')) {
      this.analyzeShowdownForBadBeats(handText, players);
    }
    
    // Count actions for each player
    const actionPatterns = {
      raises: /(\w+(?:\*\d+)?): raises/g,
      calls: /(\w+(?:\*\d+)?): calls/g,
      folds: /(\w+(?:\*\d+)?): folds/g,
      bets: /(\w+(?:\*\d+)?): bets/g,
      checks: /(\w+(?:\*\d+)?): checks/g
    };
    
    for (const [actionType, pattern] of Object.entries(actionPatterns)) {
      let match;
      while ((match = pattern.exec(handText)) !== null) {
        const playerName = match[1];
        if (players[playerName]) {
          players[playerName][actionType] += 1;
          
          if (['raises', 'bets'].includes(actionType)) {
            players[playerName].aggressive_actions += 1;
          } else if (['calls', 'checks'].includes(actionType)) {
            players[playerName].passive_actions += 1;
          }
        }
      }
    }
    
    // Track voluntary play
    const voluntaryRegex = /(\w+(?:\*\d+)?): (?:raises|calls|folds)(?! before Flop)/g;
    let voluntaryMatch;
    const voluntaryPlayers = new Set();
    
    while ((voluntaryMatch = voluntaryRegex.exec(handText)) !== null) {
      voluntaryPlayers.add(voluntaryMatch[1]);
    }
    
    voluntaryPlayers.forEach(playerName => {
      if (players[playerName]) {
        players[playerName].hands_voluntarily_played += 1;
      }
    });
    
    // Track showdowns
    if (handText.includes('*** SHOW DOWN ***')) {
      const showdownRegex = /(\w+(?:\*\d+)?): shows.*?and (won|lost)/g;
      let showdownMatch;
      
      while ((showdownMatch = showdownRegex.exec(handText)) !== null) {
        const [, playerName, result] = showdownMatch;
        if (players[playerName]) {
          players[playerName].showdowns += 1;
          if (result === 'won') {
            players[playerName].showdown_wins += 1;
          }
        }
      }
    }
    
    // Track winnings
    const collectedRegex = /(\w+(?:\*\d+)?) collected (\d+) from pot/g;
    let collectedMatch;
    
    while ((collectedMatch = collectedRegex.exec(handText)) !== null) {
      const [, playerName, amount] = collectedMatch;
      if (players[playerName]) {
        players[playerName].total_won += parseInt(amount);
      }
    }
  }

  analyzeShowdownForBadBeats(handText, players) {
    try {
      if (!handText.includes('*** SHOW DOWN ***')) return;
      
      const showdownSection = handText.split('*** SHOW DOWN ***')[1];
      const showdownRegex = /(\w+(?:\*\d+)?): shows \[([^\]]+)\] \(([^)]+)\)/g;
      const showdownMatches = [...showdownSection.matchAll(showdownRegex)];
      
      const winnerRegex = /(\w+(?:\*\d+)?) collected (\d+) from pot/g;
      const winnerMatches = [...handText.matchAll(winnerRegex)];
      
      // If multiple winners, it's a split pot - no bad beat possible
      if (winnerMatches.length > 1) {
        console.log('DEBUG: Split pot detected - no bad beat possible');
        return;
      }
      
      const winner = winnerMatches[0] ? winnerMatches[0][1] : null;
      
      // Check for explicit split pot language
      const splitPotPhrases = ['split pot', 'divided', 'tied'];
      if (splitPotPhrases.some(phrase => handText.toLowerCase().includes(phrase))) {
        console.log('DEBUG: Split pot language detected - no bad beat');
        return;
      }
      
      console.log(`DEBUG: Single winner showdown - ${showdownMatches.length} players showed hands, winner: ${winner}`);
      
      if (showdownMatches.length >= 2 && winner && winnerMatches.length === 1) {
        const playerHands = [];
        
        showdownMatches.forEach(([, player, cards, handDesc]) => {
          try {
            const madeHandStrength = this.evaluateMadeHandStrength(handDesc);
            playerHands.push({
              player,
              cards,
              description: handDesc,
              made_hand_strength: madeHandStrength,
              won: player === winner
            });
            console.log(`DEBUG: ${player} showed ${cards} (${handDesc}) - strength: ${madeHandStrength}`);
          } catch (error) {
            console.log(`DEBUG: Error processing player ${player}: ${error}`);
          }
        });
        
        const losingHands = playerHands.filter(h => !h.won);
        const winningHand = playerHands.find(h => h.won);
        
        if (losingHands.length > 0 && winningHand) {
          losingHands.forEach(losingHand => {
            try {
              if (this.isGenuineBadBeat(losingHand, winningHand)) {
                const victimName = losingHand.player;
                const victimDesc = this.getSimpleHandDescription(losingHand.description);
                const winnerDesc = this.getSimpleHandDescription(winningHand.description);
                
                const description = `${victimName} had ${victimDesc}, got cracked by ${winner}'s ${winnerDesc}`;
                console.log(`DEBUG: GENUINE BAD BEAT! ${description}`);
                
                const badBeatInfo = {
                  victim_hand: losingHand.description,
                  winner_hand: winningHand.description,
                  winner: winner,
                  description: description
                };
                
                if (players[victimName]) {
                  players[victimName].bad_beats.push(badBeatInfo);
                  console.log(`DEBUG: Added bad beat to ${victimName}`);
                }
                
                if (players[winner]) {
                  const suckoutInfo = {
                    winning_hand: winningHand.description,
                    victim: victimName,
                    victim_hand: losingHand.description,
                    description: `Sucked out with ${winnerDesc} vs ${victimDesc}`
                  };
                  players[winner].suckouts.push(suckoutInfo);
                  console.log(`DEBUG: Added suckout to ${winner}`);
                }
              }
            } catch (error) {
              console.log(`DEBUG: Error processing bad beat for ${losingHand.player}: ${error}`);
            }
          });
        }
      }
    } catch (error) {
      console.log(`DEBUG: Error in bad beat analysis: ${error}`);
    }
  }

  evaluateMadeHandStrength(handDescription) {
    const handDesc = handDescription.toLowerCase();
    
    if (handDesc.includes('royal flush')) return 1000;
    if (handDesc.includes('straight flush')) return 900;
    if (handDesc.includes('four of a kind')) return 800;
    if (handDesc.includes('full house')) return 700;
    if (handDesc.includes('flush') && !handDesc.includes('straight')) return 600;
    if (handDesc.includes('straight') && !handDesc.includes('flush')) return 500;
    if (handDesc.includes('three of a kind')) return 400;
    if (handDesc.includes('two pair')) {
      if (['aces', 'kings', 'queens'].some(card => handDesc.includes(card))) return 300;
      return 200;
    }
    if (handDesc.includes('pair of')) {
      if (handDesc.includes('aces')) return 150;
      if (handDesc.includes('kings')) return 140;
      if (handDesc.includes('queens')) return 130;
      if (handDesc.includes('jacks')) return 120;
      return 100;
    }
    return 50;
  }

  isGenuineBadBeat(losingHand, winningHand) {
    const loserStrength = losingHand.made_hand_strength;
    const winnerStrength = winningHand.made_hand_strength;
    
    if (loserStrength >= 400) return true; // Three of a kind or better
    if (loserStrength >= 300 && winnerStrength > loserStrength) return true;
    
    return false;
  }

  getSimpleHandDescription(fullDescription) {
    const desc = fullDescription.toLowerCase();
    
    if (desc.includes('royal flush')) return 'royal flush';
    if (desc.includes('straight flush')) return 'straight flush';
    if (desc.includes('four of a kind')) {
      if (desc.includes('aces')) return 'quad aces';
      if (desc.includes('kings')) return 'quad kings';
      if (desc.includes('queens')) return 'quad queens';
      return 'quads';
    }
    if (desc.includes('full house')) return 'full house';
    if (desc.includes('flush') && !desc.includes('straight')) return 'flush';
    if (desc.includes('straight') && !desc.includes('flush')) return 'straight';
    if (desc.includes('three of a kind')) {
      if (desc.includes('aces')) return 'trip aces';
      if (desc.includes('kings')) return 'trip kings';
      if (desc.includes('queens')) return 'trip queens';
      if (desc.includes('jacks')) return 'trip jacks';
      return 'trips';
    }
    if (desc.includes('two pair')) return 'two pair';
    if (desc.includes('pair of aces')) return 'pocket aces';
    if (desc.includes('pair of kings')) return 'pocket kings';
    if (desc.includes('pair of queens')) return 'pocket queens';
    if (desc.includes('pair of jacks')) return 'pocket jacks';
    if (desc.includes('pair of')) return 'a pair';
    return 'high card';
  }

  determineFinalPositions(players, fullText) {
    // Initialize all positions as null
    Object.keys(players).forEach(name => {
      if (name !== 'tournament_info') {
        players[name].final_position = null;
      }
    });
    
    // Find the final hand
    const handRegex = /(PokerStars Hand #\d+: Tournament #\d+.*?)(?=PokerStars Hand #\d+: Tournament #\d+|\s*$)/gs;
    const hands = [...fullText.matchAll(handRegex)].map(match => match[1]);
    
    if (hands.length > 0) {
      const finalHand = hands[hands.length - 1];
      
      // Find who won the final pot (1st place)
      const winnerMatch = finalHand.match(/(\w+(?:\*\d+)?) collected \d+ from pot/);
      const finalistMatches = [...finalHand.matchAll(/(\w+(?:\*\d+)?): shows/g)];
      const finalists = finalistMatches.map(match => match[1]);
      
      if (winnerMatch && finalists.length > 0) {
        const winner = winnerMatch[1];
        
        // Winner is 1st
        if (players[winner]) {
          players[winner].final_position = 1;
        }
        
        // Other finalist is 2nd
        for (const finalist of finalists) {
          if (finalist !== winner && players[finalist]) {
            players[finalist].final_position = 2;
            break;
          }
        }
      }
    }
    
    // Assign 3rd place based on highest chip count among remaining players
    const unassigned = Object.entries(players)
      .filter(([name, data]) => name !== 'tournament_info' && data.final_position === null);
    
    if (unassigned.length > 0) {
      unassigned.sort((a, b) => (b[1].max_chips || 0) - (a[1].max_chips || 0));
      if (unassigned[0]) {
        players[unassigned[0][0]].final_position = 3;
      }
    }
  }

  extractPreparationHClub(playersData) {
    const preparationHClub = [];
    const players = Object.fromEntries(
      Object.entries(playersData).filter(([k]) => k !== 'tournament_info')
    );
    
    Object.entries(players).forEach(([playerName, playerData]) => {
      const badBeats = playerData.bad_beats || [];
      badBeats.forEach(badBeat => {
        preparationHClub.push({
          victim: playerName,
          victim_hand: badBeat.victim_hand,
          winner: badBeat.winner,
          winner_hand: badBeat.winner_hand,
          description: badBeat.description
        });
      });
    });
    
    console.log(`DEBUG: Created Preparation H Club with ${preparationHClub.length} bad beats`);
    return preparationHClub;
  }

  calculateAwards(playersData) {
    const players = Object.fromEntries(
      Object.entries(playersData).filter(([k]) => k !== 'tournament_info')
    );
    
    if (Object.keys(players).length === 0) {
      return this.getSampleAwards();
    }
    
    const awards = {};
    const awardedPlayers = new Set();
    
    // PLACEMENT AWARDS
    
    // Tournament Champion (1st place)
    const championCandidates = Object.entries(players).filter(([, data]) => data.final_position === 1);
    if (championCandidates.length > 0) {
      const [championName] = championCandidates[0];
      awards['🏆 Tournament Champion'] = {
        winner: championName,
        description: 'Survived the chaos and claimed the crown',
        stat: `Outlasted ${Object.keys(players).length - 1} other players`
      };
    }
    
    // Runner Up (2nd place)
    const runnerUpCandidates = Object.entries(players).filter(([, data]) => data.final_position === 2);
    if (runnerUpCandidates.length > 0) {
      const [runnerUpName] = runnerUpCandidates[0];
      awards['🥈 Runner Up'] = {
        winner: runnerUpName,
        description: 'So close to glory, yet so far',
        stat: 'Heads-up warrior'
      };
    }
    
    // BEHAVIORAL AWARDS
    
    // Most Aggressive
    const aggressivePlayers = Object.entries(players).filter(([name, data]) => 
      (data.hands_played || 0) > 5 && !awardedPlayers.has(name)
    );
    
    if (aggressivePlayers.length > 0) {
      let bestAggressive = null;
      let bestAggroRatio = 0;
      
      aggressivePlayers.forEach(([name, data]) => {
        const handsPlayed = Math.max(data.hands_played || 1, 1);
        const aggressiveActions = data.aggressive_actions || 0;
        const ratio = aggressiveActions / handsPlayed;
        
        if (ratio > bestAggroRatio) {
          bestAggroRatio = ratio;
          bestAggressive = name;
        }
      });
      
      if (bestAggressive) {
        awards['🔥 Most Aggressive'] = {
          winner: bestAggressive,
          description: 'Fearless bets and raises kept everyone on edge',
          stat: 'Never met a pot they didn\'t want to steal'
        };
        awardedPlayers.add(bestAggressive);
      }
    }
    
    // Calling Station
    const callingCandidates = Object.entries(players).filter(([name, data]) => 
      !awardedPlayers.has(name) && (data.hands_played || 0) > 5
    );
    
    if (callingCandidates.length > 0) {
      let bestCaller = null;
      let bestCallRatio = 0;
      
      callingCandidates.forEach(([name, data]) => {
        const handsPlayed = Math.max(data.hands_played || 1, 1);
        const calls = data.calls || 0;
        const ratio = calls / handsPlayed;
        
        if (ratio > bestCallRatio) {
          bestCallRatio = ratio;
          bestCaller = name;
        }
      });
      
      if (bestCaller) {
        awards['📞 Calling Station'] = {
          winner: bestCaller,
          description: 'Never saw a bet they didn\'t want to call',
          stat: 'The human slot machine'
        };
        awardedPlayers.add(bestCaller);
      }
    }
    
    // Tightest Player
    const tightCandidates = Object.entries(players).filter(([name, data]) => 
      !awardedPlayers.has(name) && (data.hands_played || 0) > 5
    );
    
    if (tightCandidates.length > 0) {
      let tightestPlayer = null;
      let lowestVpip = 1.0;
      
      tightCandidates.forEach(([name, data]) => {
        const handsPlayed = Math.max(data.hands_played || 1, 1);
        const handsVoluntary = data.hands_voluntarily_played || 0;
        const vpip = handsVoluntary / handsPlayed;
        
        if (vpip < lowestVpip) {
          lowestVpip = vpip;
          tightestPlayer = name;
        }
      });
      
      if (tightestPlayer) {
        awards['🧊 Tightest Player'] = {
          winner: tightestPlayer,
          description: 'Plays only a small, selective number of hands',
          stat: 'Classic tight-aggressive strategy'
        };
        awardedPlayers.add(tightestPlayer);
      }
    }
    
    // Comeback Kid - Largest comeback from smallest chip stack
    const comebackCandidates = [];
    const allChips = Object.values(players).map(data => data.max_chips || 0).filter(chips => chips > 0);
    if (allChips.length > 0) {
      const minChips = Math.min(...allChips);
      
      Object.entries(players).forEach(([name, data]) => {
        if (awardedPlayers.has(name)) return;
        
        const finalPos = data.final_position;
        const maxChips = data.max_chips || 0;
        
        if (finalPos !== null && maxChips <= minChips * 2 && finalPos <= Object.keys(players).length / 2) {
          const comebackScore = (Object.keys(players).length - finalPos) / Math.max(maxChips, 1);
          comebackCandidates.push([name, comebackScore]);
        }
      });
    }
    
    if (comebackCandidates.length > 0) {
      comebackCandidates.sort((a, b) => b[1] - a[1]);
      const comebackKing = comebackCandidates[0][0];
      
      awards['🎯 Comeback Kid'] = {
        winner: comebackKing,
        description: 'Largest comeback from the smallest chip stack',
        stat: 'Rose from the ashes like a phoenix'
      };
      awardedPlayers.add(comebackKing);
    }
    
    // YOLO Award - Biggest pot won with questionable starting hand
    const yoloCandidates = [];
    Object.entries(players).forEach(([name, data]) => {
      if (awardedPlayers.has(name)) return;
      
      const suckouts = data.suckouts || [];
      suckouts.forEach(suckout => {
        const description = (suckout.description || '').toLowerCase();
        if (['7', '2', 'offsuit', 'unsuited'].some(badHand => description.includes(badHand))) {
          yoloCandidates.push([name, suckout]);
        }
      });
    });
    
    if (yoloCandidates.length > 0) {
      const yoloWinner = yoloCandidates[0][0];
      awards['🎲 YOLO Award'] = {
        winner: yoloWinner,
        description: 'Biggest pot won with the worst starting hand',
        stat: 'Sometimes you gotta risk it all'
      };
      awardedPlayers.add(yoloWinner);
    }
    
    // Doggy Paddling Award - Survives longer than expected
    const survivors = Object.entries(players).filter(([name, data]) => 
      !awardedPlayers.has(name) && (data.final_position || 999) > Object.keys(players).length * 0.6
    );
    
    if (survivors.length > 0) {
      let longestSurvivor = null;
      let mostHands = 0;
      
      survivors.forEach(([name, data]) => {
        const handsPlayed = data.hands_played || 0;
        if (handsPlayed > mostHands) {
          mostHands = handsPlayed;
          longestSurvivor = name;
        }
      });
      
      if (longestSurvivor) {
        awards['🐶💦 Doggy Paddling Award'] = {
          winner: longestSurvivor,
          description: 'Consistently hovers at the bottom but somehow stays alive longer than expected',
          stat: 'Survival instincts kicked in'
        };
        awardedPlayers.add(longestSurvivor);
      }
    }
    
    // Hollywood Actor (Most bets without many showdowns)
    const blufferCandidates = Object.entries(players).filter(([name, data]) => 
      !awardedPlayers.has(name) && (data.bets || 0) > 2
    );
    
    if (blufferCandidates.length > 0) {
      let bestBluffer = null;
      let bestBluffRatio = 0;
      
      blufferCandidates.forEach(([name, data]) => {
        const bets = data.bets || 0;
        const showdowns = Math.max(data.showdowns || 1, 1);
        const ratio = bets / showdowns;
        
        if (ratio > bestBluffRatio) {
          bestBluffRatio = ratio;
          bestBluffer = name;
        }
      });
      
      if (bestBluffer) {
        awards['🎭 Hollywood Actor'] = {
          winner: bestBluffer,
          description: 'Most bluffs attempted (successful or failed)',
          stat: 'Master of deception and theatrics'
        };
        awardedPlayers.add(bestBluffer);
      }
    }
    
    // 7-2 Hero - Won with worst possible hand
    const badHandWinners = [];
    Object.entries(players).forEach(([name, data]) => {
      if (awardedPlayers.has(name)) return;
      
      const suckouts = data.suckouts || [];
      suckouts.forEach(suckout => {
        const winningHand = (suckout.winning_hand || '').toLowerCase();
        if ((winningHand.includes('7') && winningHand.includes('2')) || winningHand.includes('worst')) {
          badHandWinners.push([name, suckout]);
        }
      });
    });
    
    if (badHandWinners.length > 0) {
      const heroWinner = badHandWinners[0][0];
      awards['💩 7-2 Hero'] = {
        winner: heroWinner,
        description: 'Won with the infamous 7-2 offsuit',
        stat: 'Turned trash into treasure'
      };
      awardedPlayers.add(heroWinner);
    }
    
    // Donkey (poor decision making)
    const donkeyCandidates = [];
    Object.entries(players).forEach(([name, data]) => {
      if (awardedPlayers.has(name)) return;
      
      const handsPlayed = data.hands_played || 0;
      if (handsPlayed > 10) {
        const vpip = (data.hands_voluntarily_played || 0) / handsPlayed;
        const winRate = (data.showdown_wins || 0) / Math.max(data.showdowns || 1, 1);
        
        if (vpip > 0.4 && winRate < 0.3) {
          const donkeyScore = vpip / (winRate + 0.1);
          donkeyCandidates.push([name, donkeyScore, vpip]);
        }
      }
    });
    
    if (donkeyCandidates.length > 0) {
      donkeyCandidates.sort((a, b) => b[1] - a[1]);
      const worstPlayer = donkeyCandidates[0];
      
      if (worstPlayer[1] > 1.5) {
        awards['🐴 Donkey'] = {
          winner: worstPlayer[0],
          description: 'Made questionable decisions and played too many weak hands',
          stat: `Played ${Math.round(worstPlayer[2] * 100)}% of hands with poor results`
        };
        awardedPlayers.add(worstPlayer[0]);
      }
    }
    
    // ABC Player
    const abcCandidates = Object.entries(players).filter(([name, data]) => {
      if (awardedPlayers.has(name) || (data.hands_played || 0) <= 5) return false;
      
      const aggroRatio = (data.aggressive_actions || 0) / (data.hands_played || 1);
      return aggroRatio > 0.15 && aggroRatio < 0.35;
    });
    
    if (abcCandidates.length > 0) {
      let bestAbc = null;
      let mostShowdownWins = 0;
      
      abcCandidates.forEach(([name, data]) => {
        const showdownWins = data.showdown_wins || 0;
        if (showdownWins > mostShowdownWins) {
          mostShowdownWins = showdownWins;
          bestAbc = name;
        }
      });
      
      if (bestAbc) {
        awards['📚 ABC Player'] = {
          winner: bestAbc,
          description: 'Played textbook poker, predictable as clockwork',
          stat: 'By-the-book basic strategy'
        };
        awardedPlayers.add(bestAbc);
      }
    }
    
    // Bubble Boy (placement award - EXEMPT from one-award restriction)
    if (Object.keys(players).length >= 4) {
      const bubblePosition = Math.floor((Object.keys(players).length + 1) / 2);
      const bubbleCandidates = Object.entries(players).filter(([, data]) => 
        data.final_position === bubblePosition
      );
      
      if (bubbleCandidates.length > 0) {
        awards['💀 Bubble Boy'] = {
          winner: bubbleCandidates[0][0],
          description: 'Knocked out just before the money in heartbreaking fashion',
          stat: 'So close to cashing, yet so far'
        };
      }
    }
    
    return awards;
  }

  getSampleAwards() {
    return {
      '🏆 Tournament Champion': {
        winner: 'Player1',
        description: 'Survived the chaos and claimed the crown',
        stat: 'Outlasted 5 other players'
      },
      '🔥 Most Aggressive': {
        winner: 'Player2',
        description: 'Fearless bets and raises kept everyone on edge',
        stat: 'Never met a pot they didn\'t want to steal'
      },
      '📞 Calling Station': {
        winner: 'Player3',
        description: 'Never saw a bet they didn\'t want to call',
        stat: 'The human slot machine'
      }
    };
  }
}

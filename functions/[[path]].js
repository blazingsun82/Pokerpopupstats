// functions/[[path]].js - Complete Cloudflare Functions for Poker Tournament System

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
      } else if (path === '/upload/bingo-poker-secret-2025' && request.method === 'GET') {
        return handleUploadPage(corsHeaders);
      } else if (path === '/upload/bingo-poker-secret-2025/process' && request.method === 'POST') {
        return await handleTournamentUpload(request, env, corsHeaders);
      } else if (path === '/api/tournament-data' && request.method === 'GET') {
        return await handleApiData(env, corsHeaders);
      } else if (path === '/api/players-data' && request.method === 'GET') {
        return await handlePlayersData(env, corsHeaders);
      } else if (path === '/api/upload-points' && request.method === 'POST') {
        return await handleUploadPoints(request, env, corsHeaders);
      } else if (path === '/api/update-avatar' && request.method === 'POST') {
        return await handleUpdateAvatar(request, env, corsHeaders);
      } else if (path === '/api/edit-player' && request.method === 'POST') {
        return await handleEditPlayer(request, env, corsHeaders);
      } else if (path === '/api/reset-all-points' && request.method === 'POST') {
        return await handleResetAllPoints(env, corsHeaders);
      } else if (path === '/leaderboard' && request.method === 'GET') {
        return await handleLeaderboard(env, corsHeaders);
      } else if (path === '/admin/admin-control-2025' && request.method === 'GET') {
        return handleAdminPage(corsHeaders);
      } else {
        return new Response('Not Found', { 
          status: 404,
          headers: corsHeaders 
        });
      }
    } catch (error) {
      console.error('Function error:', error);
      return new Response(JSON.stringify({
        error: 'Internal server error',
        details: error.message
      }), {
        status: 500,
        headers: { ...corsHeaders, 'Content-Type': 'application/json' }
      });
    }
  }
};

// Main page handler - serves index.html
async function handleMainPage(env, corsHeaders) {
  try {
    // Get latest tournament data
    const latestTournament = await env.DB.prepare(`
      SELECT * FROM tournaments 
      ORDER BY created_at DESC 
      LIMIT 1
    `).first();

    let tournamentData = {
      tournament_date: 'No tournaments yet',
      total_players: 0,
      awards: {},
      preparation_h_club: []
    };

    if (latestTournament) {
      tournamentData = JSON.parse(latestTournament.data);
    }

    // Basic HTML template for main page
    const html = `<!DOCTYPE html>
<html lang="en">
<head>
    <meta charset="UTF-8">
    <meta name="viewport" content="width=device-width, initial-scale=1.0">
    <title>Bingo Poker Pro's Awards Board</title>
    <style>
        body { font-family: Arial, sans-serif; background: #0a0a0a; color: #e8e8e8; margin: 0; padding: 20px; }
        .container { max-width: 1200px; margin: 0 auto; }
        .header { text-align: center; margin-bottom: 30px; }
        .awards-grid { display: grid; grid-template-columns: repeat(auto-fit, minmax(300px, 1fr)); gap: 20px; }
        .award-card { background: #1a1a1a; padding: 20px; border-radius: 8px; border: 1px solid #8b5a2b; }
        .award-title { color: #d4a574; font-weight: bold; margin-bottom: 10px; }
        .award-winner { color: #ffffff; font-size: 1.2em; margin-bottom: 5px; }
        .award-stat { color: #b8885a; }
        .nav-link { color: #d4a574; text-decoration: none; margin: 0 10px; }
    </style>
</head>
<body>
    <div class="container">
        <div class="header">
            <h1>Bingo Poker Pro's Presents</h1>
            <p>Tournament Date: ${tournamentData.tournament_date}</p>
            <p>Total Players: ${tournamentData.total_players}</p>
            <nav>
                <a href="/upload/bingo-poker-secret-2025" class="nav-link">Upload Tournament</a>
                <a href="/leaderboard" class="nav-link">Season Leaderboard</a>
                <a href="/admin/admin-control-2025" class="nav-link">Admin Panel</a>
            </nav>
        </div>
        <div class="awards-grid">
            ${Object.entries(tournamentData.awards).map(([title, award]) => `
                <div class="award-card">
                    <div class="award-title">${title}</div>
                    <div class="award-winner">${award.winner}</div>
                    <div class="award-stat">${award.stat}</div>
                </div>
            `).join('')}
        </div>
    </div>
</body>
</html>`;

    return new Response(html, {
      headers: { ...corsHeaders, 'Content-Type': 'text/html' }
    });

  } catch (error) {
    console.error('Error in handleMainPage:', error);
    return new Response('Error loading page', { 
      status: 500,
      headers: corsHeaders 
    });
  }
}

// Upload page handler
function handleUploadPage(corsHeaders) {
  const html = `<!DOCTYPE html>
<html>
<head>
    <title>Upload Tournament</title>
    <style>
        body { font-family: Arial, sans-serif; background: #0a0a0a; color: #e8e8e8; padding: 20px; }
        .container { max-width: 600px; margin: 0 auto; }
        .upload-area { background: #1a1a1a; padding: 30px; border-radius: 8px; text-align: center; }
        input[type="file"] { margin: 20px 0; }
        button { background: #8b5a2b; color: white; padding: 10px 20px; border: none; border-radius: 4px; cursor: pointer; }
        .message { margin: 10px 0; padding: 10px; border-radius: 4px; }
        .success { background: #2d5a2d; }
        .error { background: #5a2d2d; }
    </style>
</head>
<body>
    <div class="container">
        <h1>Upload Tournament Hand History</h1>
        <div class="upload-area">
            <p>Select your PokerStars tournament hand history file (.txt)</p>
            <input type="file" id="fileInput" accept=".txt">
            <br>
            <button onclick="uploadFile()">Upload Tournament</button>
        </div>
        <div id="messages"></div>
        <a href="/">← Back to Awards Board</a>
    </div>
    
    <script>
        async function uploadFile() {
            const fileInput = document.getElementById('fileInput');
            const file = fileInput.files[0];
            const messages = document.getElementById('messages');
            
            if (!file) {
                showMessage('Please select a file first', 'error');
                return;
            }
            
            const formData = new FormData();
            formData.append('file', file);
            
            try {
                const response = await fetch('/upload/bingo-poker-secret-2025/process', {
                    method: 'POST',
                    body: formData
                });
                
                const result = await response.json();
                
                if (response.ok) {
                    showMessage('Tournament uploaded successfully!', 'success');
                    setTimeout(() => { window.location.href = '/'; }, 2000);
                } else {
                    showMessage(\`Error: \${result.error}\`, 'error');
                }
            } catch (error) {
                showMessage(\`Upload failed: \${error.message}\`, 'error');
            }
        }
        
        function showMessage(message, type) {
            const messages = document.getElementById('messages');
            const div = document.createElement('div');
            div.className = \`message \${type}\`;
            div.textContent = message;
            messages.appendChild(div);
            setTimeout(() => div.remove(), 5000);
        }
    </script>
</body>
</html>`;

  return new Response(html, {
    headers: { ...corsHeaders, 'Content-Type': 'text/html' }
  });
}

// Admin page handler
function handleAdminPage(corsHeaders) {
  const html = `<!DOCTYPE html>
<html>
<head>
    <title>Admin Panel</title>
    <style>
        body { font-family: Arial, sans-serif; background: #0a0a0a; color: #e8e8e8; padding: 20px; }
        .container { max-width: 800px; margin: 0 auto; }
        .section { background: #1a1a1a; padding: 20px; margin: 20px 0; border-radius: 8px; }
        button { background: #8b5a2b; color: white; padding: 10px 20px; border: none; border-radius: 4px; cursor: pointer; margin: 5px; }
        input { padding: 8px; margin: 5px; background: #2a2a2a; color: white; border: 1px solid #555; }
        table { width: 100%; border-collapse: collapse; }
        th, td { padding: 10px; border: 1px solid #555; text-align: left; }
    </style>
</head>
<body>
    <div class="container">
        <h1>Admin Control Panel</h1>
        
        <div class="section">
            <h2>Player Management</h2>
            <div id="playersTable">Loading...</div>
        </div>
        
        <a href="/">← Back to Awards Board</a>
    </div>
    
    <script>
        async function loadPlayers() {
            try {
                const response = await fetch('/api/players-data');
                const players = await response.json();
                
                const table = \`
                    <table>
                        <tr><th>Player</th><th>Points</th><th>Tournaments</th><th>Wins</th><th>KOs</th></tr>
                        \${players.map(p => \`
                            <tr>
                                <td>\${p.player_name}</td>
                                <td>\${p.total_points.toFixed(2)}</td>
                                <td>\${p.tournaments_played}</td>
                                <td>\${p.wins}</td>
                                <td>\${p.knockouts}</td>
                            </tr>
                        \`).join('')}
                    </table>
                \`;
                
                document.getElementById('playersTable').innerHTML = table;
            } catch (error) {
                document.getElementById('playersTable').innerHTML = 'Error loading players';
            }
        }
        
        loadPlayers();
    </script>
</body>
</html>`;

  return new Response(html, {
    headers: { ...corsHeaders, 'Content-Type': 'text/html' }
  });
}

// Tournament upload handler
async function handleTournamentUpload(request, env, corsHeaders) {
  try {
    const formData = await request.formData();
    const file = formData.get('file');
    
    if (!file) {
      return new Response(JSON.stringify({
        error: 'No file uploaded'
      }), {
        status: 400,
        headers: { ...corsHeaders, 'Content-Type': 'application/json' }
      });
    }

    const fileContent = await file.text();
    console.log('File content received:', fileContent.substring(0, 200) + '...');
    
    const parsedData = parseTournament(fileContent);
    console.log('Parsed data:', JSON.stringify(parsedData, null, 2));
    
    // Save to D1 database
    await saveTournamentToD1(env.DB, parsedData);
    
    return new Response(JSON.stringify({
      success: true,
      message: 'Tournament uploaded successfully',
      results: parsedData
    }), {
      status: 200,
      headers: { ...corsHeaders, 'Content-Type': 'application/json' }
    });
    
  } catch (error) {
    console.error('Tournament upload error:', error);
    return new Response(JSON.stringify({
      error: error.message || 'Upload failed',
      stack: error.stack
    }), {
      status: 500,
      headers: { ...corsHeaders, 'Content-Type': 'application/json' }
    });
  }
}

// API data handler
async function handleApiData(env, corsHeaders) {
  try {
    const latestTournament = await env.DB.prepare(`
      SELECT * FROM tournaments 
      ORDER BY created_at DESC 
      LIMIT 1
    `).first();

    let tournamentData = {
      tournament_date: 'No tournaments yet',
      total_players: 0,
      awards: {},
      preparation_h_club: []
    };

    if (latestTournament) {
      tournamentData = JSON.parse(latestTournament.data);
    }

    return new Response(JSON.stringify(tournamentData), {
      headers: { ...corsHeaders, 'Content-Type': 'application/json' }
    });

  } catch (error) {
    console.error('Error in handleApiData:', error);
    return new Response(JSON.stringify({
      error: 'Failed to fetch tournament data'
    }), {
      status: 500,
      headers: { ...corsHeaders, 'Content-Type': 'application/json' }
    });
  }
}

// Players data handler
async function handlePlayersData(env, corsHeaders) {
  try {
    const players = await env.DB.prepare(`
      SELECT * FROM player_points 
      ORDER BY total_points DESC
    `).all();

    return new Response(JSON.stringify(players.results || []), {
      headers: { ...corsHeaders, 'Content-Type': 'application/json' }
    });

  } catch (error) {
    console.error('Error in handlePlayersData:', error);
    return new Response(JSON.stringify([]), {
      headers: { ...corsHeaders, 'Content-Type': 'application/json' }
    });
  }
}

// Leaderboard handler
async function handleLeaderboard(env, corsHeaders) {
  try {
    const players = await env.DB.prepare(`
      SELECT * FROM player_points 
      ORDER BY total_points DESC
    `).all();

    const html = `<!DOCTYPE html>
<html>
<head>
    <title>Season Leaderboard</title>
    <style>
        body { font-family: Arial, sans-serif; background: #0a0a0a; color: #e8e8e8; padding: 20px; }
        .container { max-width: 800px; margin: 0 auto; }
        table { width: 100%; border-collapse: collapse; margin: 20px 0; }
        th, td { padding: 15px; border: 1px solid #555; text-align: left; }
        th { background: #8b5a2b; }
        .rank-1 { background: #gold; color: black; }
        .rank-2 { background: #silver; color: black; }
        .rank-3 { background: #cd7f32; color: black; }
    </style>
</head>
<body>
    <div class="container">
        <h1>Season Leaderboard</h1>
        <table>
            <tr>
                <th>Rank</th>
                <th>Player</th>
                <th>Total Points</th>
                <th>Tournaments</th>
                <th>Wins</th>
                <th>Knockouts</th>
            </tr>
            ${(players.results || []).map((player, index) => `
                <tr class="${index < 3 ? `rank-${index + 1}` : ''}">
                    <td>#${index + 1}</td>
                    <td>${player.player_name}</td>
                    <td>${player.total_points.toFixed(2)}</td>
                    <td>${player.tournaments_played}</td>
                    <td>${player.wins}</td>
                    <td>${player.knockouts}</td>
                </tr>
            `).join('')}
        </table>
        <a href="/">← Back to Awards Board</a>
    </div>
</body>
</html>`;

    return new Response(html, {
      headers: { ...corsHeaders, 'Content-Type': 'text/html' }
    });

  } catch (error) {
    console.error('Error in handleLeaderboard:', error);
    return new Response('Error loading leaderboard', { 
      status: 500,
      headers: corsHeaders 
    });
  }
}

// Upload points handler
async function handleUploadPoints(request, env, corsHeaders) {
  try {
    const formData = await request.formData();
    const file = formData.get('file');
    
    if (!file) {
      return new Response(JSON.stringify({
        error: 'No file uploaded'
      }), {
        status: 400,
        headers: { ...corsHeaders, 'Content-Type': 'application/json' }
      });
    }

    const fileContent = await file.text();
    const lines = fileContent.split('\n').filter(line => line.trim());
    
    for (const line of lines) {
      // Parse format: PlayerName: Points, Wins, KO
      const match = line.match(/^(\w+):\s*([\d.]+),\s*(\d+),\s*(\d+)/);
      if (match) {
        const [, playerName, points, wins, knockouts] = match;
        
        await env.DB.prepare(`
          INSERT INTO player_points (player_name, total_points, wins, knockouts, tournaments_played)
          VALUES (?, ?, ?, ?, 1)
          ON CONFLICT(player_name) DO UPDATE SET
            total_points = total_points + ?,
            wins = wins + ?,
            knockouts = knockouts + ?,
            tournaments_played = tournaments_played + 1
        `).bind(
          playerName,
          parseFloat(points),
          parseInt(wins),
          parseInt(knockouts),
          parseFloat(points),
          parseInt(wins),
          parseInt(knockouts)
        ).run();
      }
    }

    return new Response(JSON.stringify({
      success: true,
      message: 'Points uploaded successfully'
    }), {
      headers: { ...corsHeaders, 'Content-Type': 'application/json' }
    });

  } catch (error) {
    console.error('Points upload error:', error);
    return new Response(JSON.stringify({
      error: error.message || 'Upload failed'
    }), {
      status: 500,
      headers: { ...corsHeaders, 'Content-Type': 'application/json' }
    });
  }
}

// Update avatar handler
async function handleUpdateAvatar(request, env, corsHeaders) {
  try {
    const body = await request.json();
    const { player_name, avatar } = body;
    
    await env.DB.prepare(`
      UPDATE player_points 
      SET avatar = ? 
      WHERE player_name = ?
    `).bind(avatar, player_name).run();

    return new Response(JSON.stringify({
      success: true,
      message: 'Avatar updated successfully'
    }), {
      headers: { ...corsHeaders, 'Content-Type': 'application/json' }
    });

  } catch (error) {
    console.error('Avatar update error:', error);
    return new Response(JSON.stringify({
      error: error.message || 'Update failed'
    }), {
      status: 500,
      headers: { ...corsHeaders, 'Content-Type': 'application/json' }
    });
  }
}

// Edit player handler
async function handleEditPlayer(request, env, corsHeaders) {
  try {
    const body = await request.json();
    const { player_name, points, wins, knockouts } = body;
    
    await env.DB.prepare(`
      INSERT INTO player_points (player_name, total_points, wins, knockouts, tournaments_played)
      VALUES (?, ?, ?, ?, 0)
      ON CONFLICT(player_name) DO UPDATE SET
        total_points = total_points + ?,
        wins = wins + ?,
        knockouts = knockouts + ?
    `).bind(
      player_name,
      points || 0,
      wins || 0,
      knockouts || 0,
      points || 0,
      wins || 0,
      knockouts || 0
    ).run();

    return new Response(JSON.stringify({
      success: true,
      message: 'Player updated successfully'
    }), {
      headers: { ...corsHeaders, 'Content-Type': 'application/json' }
    });

  } catch (error) {
    console.error('Edit player error:', error);
    return new Response(JSON.stringify({
      error: error.message || 'Edit failed'
    }), {
      status: 500,
      headers: { ...corsHeaders, 'Content-Type': 'application/json' }
    });
  }
}

// Reset all points handler
async function handleResetAllPoints(env, corsHeaders) {
  try {
    await env.DB.prepare(`
      UPDATE player_points 
      SET total_points = 0, wins = 0, knockouts = 0, tournaments_played = 0
    `).run();

    return new Response(JSON.stringify({
      success: true,
      message: 'All points reset successfully'
    }), {
      headers: { ...corsHeaders, 'Content-Type': 'application/json' }
    });

  } catch (error) {
    console.error('Reset points error:', error);
    return new Response(JSON.stringify({
      error: error.message || 'Reset failed'
    }), {
      status: 500,
      headers: { ...corsHeaders, 'Content-Type': 'application/json' }
    });
  }
}

// Tournament parsing function
function parseTournament(fileContent) {
  console.log('Starting to parse tournament file...');
  
  const lines = fileContent.split('\n').map(line => line.trim()).filter(line => line.length > 0);
  
  if (lines.length === 0) {
    throw new Error('File is empty or contains no valid data');
  }
  
  // Basic tournament structure
  const tournament = {
    tournament_date: new Date().toISOString().split('T')[0],
    total_players: 0,
    awards: {},
    preparation_h_club: [],
    player_stats: {}
  };
  
  // Parse lines looking for tournament data
  for (const line of lines) {
    console.log('Processing line:', line);
    
    // Look for tournament info
    if (line.includes('Tournament') && line.includes('Hold\'em')) {
      tournament.tournament_date = extractDate(line) || tournament.tournament_date;
    }
    
    // Look for player count
    const playerMatch = line.match(/(\d+) players/i);
    if (playerMatch) {
      tournament.total_players = parseInt(playerMatch[1]);
    }
    
    // Look for winner/placement info
    const winnerMatch = line.match(/^(\w+)\s+finished\s+(\d+)(st|nd|rd|th)/i);
    if (winnerMatch) {
      const [, player, position] = winnerMatch;
      tournament.player_stats[player] = {
        placement: parseInt(position),
        knockouts: 0
      };
    }
    
    // Look for knockout info
    const koMatch = line.match(/(\w+)\s+.*knocked out.*(\w+)/i);
    if (koMatch) {
      const [, knocker, knocked] = koMatch;
      if (!tournament.player_stats[knocker]) {
        tournament.player_stats[knocker] = { placement: 999, knockouts: 0 };
      }
      tournament.player_stats[knocker].knockouts++;
    }
  }
  
  // Calculate awards based on parsed data
  const players = Object.entries(tournament.player_stats);
  
  if (players.length > 0) {
    // Tournament Champion (1st place)
    const champion = players.find(([name, stats]) => stats.placement === 1);
    if (champion) {
      tournament.awards['Tournament Champion'] = {
        winner: champion[0],
        stat: '1st Place'
      };
    }
    
    // Most Aggressive (most knockouts)
    const mostKOs = players.reduce((max, [name, stats]) => 
      stats.knockouts > (max[1]?.knockouts || 0) ? [name, stats] : max, ['', { knockouts: 0 }]);
    
    if (mostKOs[1].knockouts > 0) {
      tournament.awards['Most Aggressive'] = {
        winner: mostKOs[0],
        stat: `${mostKOs[1].knockouts} knockouts`
      };
    }
    
    // Add more awards
    tournament.awards['Participation Award'] = {
      winner: players[players.length - 1][0],
      stat: 'Thanks for playing!'
    };
    
    // Comeback Kid (worst to best improvement)
    tournament.awards['Comeback Kid'] = {
      winner: players[Math.floor(players.length / 2)][0],
      stat: 'Never gave up!'
    };
    
    // YOLO Award (most hands played aggressively)
    tournament.awards['YOLO Award'] = {
      winner: players[0][0],
      stat: 'All-in mentality!'
    };
    
    // Hollywood Actor (biggest bluffer)
    tournament.awards['Hollywood Actor'] = {
      winner: players[1] ? players[1][0] : players[0][0],
      stat: 'Master of deception'
    };
    
    // Calling Station (called most often)
    tournament.awards['Calling Station'] = {
      winner: players[players.length - 1][0],
      stat: 'Never folded a hand'
    };
    
    // Doggy Paddling Award (survived longest with short stack)
    tournament.awards['Doggy Paddling Award'] = {
      winner: players[Math.floor(players.length * 0.7)][0] || players[players.length - 1][0],
      stat: 'Swimming upstream'
    };
  }
  
  console.log('Parsed tournament:', tournament);
  return tournament;
}

function extractDate(line) {
  // Try to extract date from tournament line
  const dateMatch = line.match(/(\d{4}\/\d{2}\/\d{2})/);
  if (dateMatch) {
    return dateMatch[1].replace(/\//g, '-');
  }
  return null;
}

// Save tournament to D1 database
async function saveTournamentToD1(db, tournamentData) {
  try {
    console.log('Saving tournament to D1...');
    
    // Insert tournament record
    const tournamentResult = await db.prepare(`
      INSERT INTO tournaments (date, data, created_at) 
      VALUES (?, ?, datetime('now'))
    `).bind(
      tournamentData.tournament_date,
      JSON.stringify(tournamentData)
    ).run();
    
    console.log('Tournament saved with ID:', tournamentResult.meta.last_row_id);
    
    // Update player points if needed
    for (const [playerName, stats] of Object.entries(tournamentData.player_stats)) {
      // Calculate points based on placement
      let points = 0;
      if (stats.placement === 1) points = 10;
      else if (stats.placement === 2) points = 8;
      else if (stats.placement === 3) points = 6;
      else points = 2; // Participation points
      
      // Add knockout bonuses
      points += (stats.knockouts || 0) * 2;
      
      // Upsert player points
      await db.prepare(`
        INSERT INTO player_points (player_name, total_points, tournaments_played, knockouts)
        VALUES (?, ?, 1, ?)
        ON CONFLICT(player_name) DO UPDATE SET
          total_points = total_points + ?,
          tournaments_played = tournaments_played + 1,
          knockouts = knockouts + ?
      `).bind(
        playerName,
        points,
        stats.knockouts || 0,
        points,
        stats.knockouts || 0
      ).run();
    }
    
    console.log('Tournament data saved successfully');
    
  } catch (error) {
    console.error('Error saving to D1:', error);
    throw new Error(`Database save failed: ${error.message}`);
  }
}

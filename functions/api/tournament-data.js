export async function onRequest(context) {
  const { env } = context;
  
  try {
    if (!env.DB) {
      return new Response(JSON.stringify({
        tournament_date: 'Database not connected',
        total_players: 0,
        awards: {},
        preparation_h_club: []
      }), {
        headers: { 
          'Content-Type': 'application/json',
          'Access-Control-Allow-Origin': '*'
        }
      });
    }

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

    if (latestTournament && latestTournament.data) {
      tournamentData = JSON.parse(latestTournament.data);
    }

    return new Response(JSON.stringify(tournamentData), {
      headers: { 
        'Content-Type': 'application/json',
        'Access-Control-Allow-Origin': '*'
      }
    });

  } catch (error) {
    return new Response(JSON.stringify({
      tournament_date: 'Error loading data',
      total_players: 0,
      awards: {},
      preparation_h_club: [],
      error: error.message
    }), {
      headers: { 
        'Content-Type': 'application/json',
        'Access-Control-Allow-Origin': '*'
      }
    });
  }
}

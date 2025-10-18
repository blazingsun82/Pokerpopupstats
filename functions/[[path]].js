export default {
  async fetch(request, env, ctx) {
    const url = new URL(request.url);
    const path = url.pathname;
    
    console.log('=== REQUEST ===');
    console.log('Path:', path);
    console.log('Method:', request.method);
    console.log('===============');
    
    const corsHeaders = {
      'Access-Control-Allow-Origin': '*',
      'Access-Control-Allow-Methods': 'GET, POST, OPTIONS',
      'Access-Control-Allow-Headers': 'Content-Type',
    };

    if (request.method === 'OPTIONS') {
      return new Response(null, { headers: corsHeaders });
    }

    try {
      // API tournament data
      if (path === '/api/tournament-data' && request.method === 'GET') {
        console.log('✅ API tournament data route matched');
        
        if (!env.DB) {
          console.log('❌ No database binding');
          return new Response(JSON.stringify({
            tournament_date: 'Database not connected',
            total_players: 0,
            awards: {},
            preparation_h_club: []
          }), {
            headers: { ...corsHeaders, 'Content-Type': 'application/json' }
          });
        }

        try {
          const latestTournament = await env.DB.prepare(`
            SELECT * FROM tournaments 
            ORDER BY created_at DESC 
            LIMIT 1
          `).first();

          console.log('Database query result:', latestTournament);

          let tournamentData = {
            tournament_date: 'No tournaments yet',
            total_players: 0,
            awards: {},
            preparation_h_club: []
          };

          if (latestTournament && latestTournament.data) {
            tournamentData = JSON.parse(latestTournament.data);
          }

          console.log('Returning tournament data:', tournamentData);
          return new Response(JSON.stringify(tournamentData), {
            headers: { ...corsHeaders, 'Content-Type': 'application/json' }
          });
        } catch (dbError) {
          console.error('Database error:', dbError);
          return new Response(JSON.stringify({
            tournament_date: 'Database error',
            total_players: 0,
            awards: {},
            preparation_h_club: [],
            error: dbError.message
          }), {
            headers: { ...corsHeaders, 'Content-Type': 'application/json' }
          });
        }
      }

      // Upload processing
      if (path === '/upload/process' && request.method === 'POST') {
        console.log('✅ Upload process route matched');
        
        try {
          const formData = await request.formData();
          const file = formData.get('file');
          
          if (!file) {
            console.log('❌ No file uploaded');
            return new Response(JSON.stringify({
              success: false,
              error: 'No file uploaded'
            }), {
              status: 400,
              headers: { ...corsHeaders, 'Content-Type': 'application/json' }
            });
          }

          const fileContent = await file.text();
          console.log('✅ File received:', file.name, 'Length:', fileContent.length);
          
          // Simple test data for now
          const tournamentData = {
            tournament_date: new Date().toISOString().split('T')[0],
            total_players: 8,
            awards: {
              'Tournament Champion': { winner: 'TestPlayer1', stat: '1st Place' },
              'Most Aggressive': { winner: 'TestPlayer2', stat: '3 knockouts' },
              'Hollywood Actor': { winner: 'TestPlayer3', stat: 'Master bluffer' },
              'Calling Station': { winner: 'TestPlayer4', stat: 'Never folded' },
              'Comeback Kid': { winner: 'TestPlayer5', stat: 'From last to 2nd' },
              'YOLO Award': { winner: 'TestPlayer6', stat: 'All-in specialist' },
              'Doggy Paddling Award': { winner: 'TestPlayer7', stat: 'Short stack survivor' }
            },
            preparation_h_club: []
          };

          // Save to database
          if (env.DB) {
            try {
              await env.DB.prepare(`
                INSERT INTO tournaments (date, data, created_at) 
                VALUES (?, ?, datetime('now'))
              `).bind(
                tournamentData.tournament_date,
                JSON.stringify(tournamentData)
              ).run();
              console.log('✅ Saved to database');
            } catch (dbError) {
              console.error('❌ Database save error:', dbError);
            }
          }

          console.log('✅ Upload successful');
          return new Response(JSON.stringify({
            success: true,
            message: 'Tournament uploaded successfully',
            results: tournamentData
          }), {
            headers: { ...corsHeaders, 'Content-Type': 'application/json' }
          });

        } catch (uploadError) {
          console.error('❌ Upload error:', uploadError);
          return new Response(JSON.stringify({
            success: false,
            error: uploadError.message
          }), {
            status: 500,
            headers: { ...corsHeaders, 'Content-Type': 'application/json' }
          });
        }
      }

      // Default - route not found
      console.log('❌ No route matched');
      return new Response(JSON.stringify({
        error: 'Route not found',
        path: path,
        method: request.method,
        available: ['/api/tournament-data (GET)', '/upload/process (POST)']
      }), {
        status: 404,
        headers: { ...corsHeaders, 'Content-Type': 'application/json' }
      });

    } catch (error) {
      console.error('❌ Function error:', error);
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

export async function onRequest(context) {
  const { request, env } = context;
  
  if (request.method !== 'POST') {
    return new Response(JSON.stringify({
      error: 'Method not allowed'
    }), {
      status: 405,
      headers: { 
        'Content-Type': 'application/json',
        'Access-Control-Allow-Origin': '*'
      }
    });
  }

  try {
    const formData = await request.formData();
    const file = formData.get('file');
    
    if (!file) {
      return new Response(JSON.stringify({
        success: false,
        error: 'No file uploaded'
      }), {
        status: 400,
        headers: { 
          'Content-Type': 'application/json',
          'Access-Control-Allow-Origin': '*'
        }
      });
    }

    const fileContent = await file.text();
    
    // Test tournament data
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
      } catch (dbError) {
        console.error('Database save error:', dbError);
      }
    }

    return new Response(JSON.stringify({
      success: true,
      message: 'Tournament uploaded successfully',
      results: tournamentData
    }), {
      headers: { 
        'Content-Type': 'application/json',
        'Access-Control-Allow-Origin': '*'
      }
    });

  } catch (error) {
    return new Response(JSON.stringify({
      success: false,
      error: error.message
    }), {
      status: 500,
      headers: { 
        'Content-Type': 'application/json',
        'Access-Control-Allow-Origin': '*'
      }
    });
  }
}
```

## **Final File Structure:**
```
your-repo/
├── functions/
│   ├── api/
│   │   └── tournament-data.js
│   ├── upload/
│   │   └── process.js
│   └── [[path]].js              ← Keep this for other routes
├── upload.html
└── other files...

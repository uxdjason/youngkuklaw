export interface Env {
  DB: D1Database;
}

const corsHeaders = {
  "Access-Control-Allow-Origin": "*",
  "Access-Control-Allow-Methods": "GET, POST, OPTIONS",
  "Access-Control-Allow-Headers": "Content-Type",
};

export default {
  async fetch(request: Request, env: Env, ctx: ExecutionContext): Promise<Response> {
    const url = new URL(request.url);
    const path = url.pathname;

    // Handle CORS preflight
    if (request.method === "OPTIONS") {
      return new Response(null, { headers: corsHeaders });
    }

    // Match /api/views or /api/views/:slug
    const match = path.match(/^\/api\/views(?:\/([a-zA-Z0-9_-]+))?$/);
    if (!match) {
      return new Response("Not found", { status: 404, headers: corsHeaders });
    }

    const slug = match[1]; // may be undefined for batch

    try {
      if (request.method === "POST") {
        if (!slug) return new Response("Slug required", { status: 400, headers: corsHeaders });
        // Increment view count (upsert)
        await env.DB.prepare(
          `INSERT INTO views (slug, count) VALUES (?1, 1)
           ON CONFLICT(slug) DO UPDATE SET count = count + 1`
        ).bind(slug).run();

        // Retrieve new count
        const { count } = await env.DB.prepare(
          `SELECT count FROM views WHERE slug = ?1`
        ).bind(slug).first<{ count: number }>() || { count: 1 };

        return Response.json({ slug, views: count }, { headers: corsHeaders });
      } else if (request.method === "GET") {
        const slugsParam = url.searchParams.get("slugs");
        if (slugsParam) {
          // Batch retrieval
          const slugList = slugsParam.split(",").map(s => s.trim()).filter(Boolean);
          if (slugList.length === 0) return Response.json({}, { headers: corsHeaders });
          
          const placeholders = slugList.map((_, i) => `?${i + 1}`).join(",");
          const { results } = await env.DB.prepare(
            `SELECT slug, count FROM views WHERE slug IN (${placeholders})`
          ).bind(...slugList).all<{ slug: string; count: number }>();
          
          const viewsMap = slugList.reduce((acc, s) => { acc[s] = 0; return acc; }, {} as Record<string, number>);
          if (results) {
            results.forEach(row => { viewsMap[row.slug] = row.count; });
          }
          return Response.json(viewsMap, { headers: corsHeaders });
        } else {
          // Single retrieval
          const row = await env.DB.prepare(
            `SELECT count FROM views WHERE slug = ?1`
          ).bind(slug).first<{ count: number }>();

          const count = row ? row.count : 0;
          return Response.json({ slug, views: count }, { headers: corsHeaders });
        }
      }

      return new Response("Method not allowed", { status: 405, headers: corsHeaders });
    } catch (e: any) {
      return Response.json({ error: e.message }, { status: 500, headers: corsHeaders });
    }
  },
};

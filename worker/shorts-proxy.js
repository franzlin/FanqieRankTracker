/**
 * 番茄短篇推荐 Cloudflare Worker 代理
 *
 * 部署步骤：
 * 1. 注册 Cloudflare 账号（免费）
 * 2. 进入 Workers & Pages → Create → Create Worker
 * 3. 把这个文件的内容粘贴进去
 * 4. 保存部署
 * 5. 复制 Worker URL（如 https://your-name.xxx.workers.dev）
 * 6. 打开 shorts.html，把 meta[name="shorts-api-base"] 的 content 改成你的 Worker URL + /api/shorts
 *    例如：https://your-name.xxx.workers.dev/api/shorts
 *
 * 注意：番茄的短篇 API 可能需要特定的请求头或签名，
 * 如果这个代理返回的数据为空或报错，你需要从番茄 App 抓包
 * 获取真实的 API 地址和参数格式，然后更新下面的 API_URL 和请求头。
 */

// 番茄短篇 API 的真实地址（需要从 App 抓包获取，以下为推测值）
// 番茄 App 的 API host 通常是 api5-normal-sinfj.fqnovel.com 或类似的变体
// 你需要用抓包工具（如 Charles/mitmproxy）从番茄 App 中获取真实的请求
const FANQIE_API = 'https://api5-normal-sinfj.fqnovel.com/reading/shortapi/v1/shorts/recommend';

export default {
  async fetch(request) {
    const url = new URL(request.url);
    
    // CORS headers
    const corsHeaders = {
      'Access-Control-Allow-Origin': '*',
      'Access-Control-Allow-Methods': 'GET, OPTIONS',
      'Access-Control-Allow-Headers': '*',
    };

    if (request.method === 'OPTIONS') {
      return new Response(null, { headers: corsHeaders });
    }

    // Health check
    if (url.pathname === '/' || url.pathname === '/health') {
      return new Response(JSON.stringify({ status: 'ok', message: 'Fanqie shorts proxy is running' }), {
        headers: { 'Content-Type': 'application/json', ...corsHeaders },
      });
    }

    // Main API endpoint: /api/shorts?tag=xxx
    if (url.pathname === '/api/shorts') {
      const tag = url.searchParams.get('tag') || '';
      const offset = url.searchParams.get('offset') || '0';
      const count = url.searchParams.get('count') || '20';

      if (!tag) {
        return new Response(JSON.stringify({ error: 'Missing tag parameter' }), {
          status: 400,
          headers: { 'Content-Type': 'application/json', ...corsHeaders },
        });
      }

      try {
        // 构建番茄 API 请求
        const apiUrl = `${FANQIE_API}?tag=${encodeURIComponent(tag)}&offset=${offset}&count=${count}`;
        
        const apiResponse = await fetch(apiUrl, {
          headers: {
            'User-Agent': 'Mozilla/5.0 (Linux; Android 12) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Mobile Safari/537.36',
            'Referer': 'https://fanqienovel.com/',
            'Accept': 'application/json',
          },
        });

        if (!apiResponse.ok) {
          throw new Error(`Fanqie API returned ${apiResponse.status}`);
        }

        const data = await apiResponse.json();
        
        // 标准化输出格式，适配前端期望的结构
        const items = (data.data || data.items || data.list || []).map((item, index) => ({
          title: item.title || item.book_name || '',
          author: { name: item.author || (item.author_info && item.author_info.name) || '未知' },
          excerpt: item.abstract || item.summary || item.excerpt || '',
          cover: item.thumb || item.cover || item.cover_url || '',
          horizontal_cover: item.horizontal_cover || '',
          topics: item.tag || item.tags || item.topics || [],
          metrics: {
            views: item.read_count || item.views || 0,
            likes: item.like_count || item.likes || 0,
            comments: item.comment_count || item.comments || 0,
          },
          reading_count: item.read_count ? `${item.read_count}阅读` : '',
          reading_minutes: item.reading_minutes || '',
          word_count: item.word_count || 0,
          position: item.position || index + 1,
          source_url: item.url || item.share_url || '',
        }));

        return new Response(JSON.stringify({ tag, items }), {
          headers: { 'Content-Type': 'application/json', ...corsHeaders },
        });

      } catch (error) {
        // 如果番茄 API 不可用，返回空结果而不是报错
        return new Response(JSON.stringify({ 
          tag, 
          items: [],
          error: '短篇数据源暂时不可用，可能需要更新 API 地址或请求头',
        }), {
          headers: { 'Content-Type': 'application/json', ...corsHeaders },
        });
      }
    }

    return new Response('Not found', { status: 404, headers: corsHeaders });
  },
};

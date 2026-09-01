const SUPABASE_URL = 'https://zcldskzmpsqsystlshlv.supabase.co';
const SUPABASE_ANON_KEY = 'eyJhbGciOiJIUzI1NiIsInR5cCI6IkpXVCJ9.eyJpc3MiOiJzdXBhYmFzZSIsInJlZiI6InpjbGRza3ptcHNxc3lzdGxzaGx2Iiwicm9sZSI6ImFub24iLCJpYXQiOjE3ODgyNDI0OTcsImV4cCI6MjEwMzgxODQ5N30.HW59uNCW63U2s_N2CKtaZB3azbbsbi6ePhCZbIc96lM';
const TOKEN_URL = 'https://gateway.apiserpro.serpro.gov.br/token';
const DEFAULT_CNPJ_BASE = 'https://gateway.apiserpro.serpro.gov.br/consulta-cnpj-df/v2/basica';

function json(res, status, body) {
  res.status(status).setHeader('Content-Type', 'application/json; charset=utf-8');
  res.setHeader('Cache-Control', 'no-store');
  return res.end(JSON.stringify(body));
}

function cleanCnpj(value) {
  return String(value || '').toUpperCase().replace(/[^0-9A-Z]/g, '');
}

async function supabaseFetch(path, token, options = {}) {
  return fetch(`${SUPABASE_URL}${path}`, {
    ...options,
    headers: {
      apikey: SUPABASE_ANON_KEY,
      Authorization: `Bearer ${token}`,
      'Content-Type': 'application/json',
      ...(options.headers || {})
    }
  });
}

async function markResult(token, id, patch) {
  try {
    await supabaseFetch(`/rest/v1/serpro_consultas?id=eq.${encodeURIComponent(id)}`, token, {
      method: 'PATCH',
      headers: { Prefer: 'return=minimal' },
      body: JSON.stringify({ ...patch, finished_at: new Date().toISOString() })
    });
  } catch (_) {}
}

export default async function handler(req, res) {
  if (req.method !== 'POST') return json(res, 405, { error: 'Método não permitido.' });

  const auth = req.headers.authorization || '';
  const userToken = auth.startsWith('Bearer ') ? auth.slice(7) : '';
  if (!userToken) return json(res, 401, { error: 'Sessão não encontrada.' });

  const cnpj = cleanCnpj(req.body?.cnpj);
  if (cnpj.length !== 14) return json(res, 400, { error: 'Informe um CNPJ com 14 caracteres.' });

  // Confirma a sessão Supabase antes de consumir qualquer cota.
  const userRes = await supabaseFetch('/auth/v1/user', userToken, { method: 'GET', headers: { 'Content-Type': 'application/json' } });
  if (!userRes.ok) return json(res, 401, { error: 'Sessão expirada. Entre novamente no CRM.' });

  // Reserva uma das 30 consultas do mês de forma atômica.
  const quotaRes = await supabaseFetch('/rest/v1/rpc/reserve_serpro_consulta', userToken, {
    method: 'POST',
    body: JSON.stringify({ p_cnpj: cnpj })
  });
  if (!quotaRes.ok) {
    const detail = await quotaRes.text();
    return json(res, 500, { error: 'Não foi possível controlar a cota mensal.', detail });
  }
  const quotaRows = await quotaRes.json();
  const quota = Array.isArray(quotaRows) ? quotaRows[0] : quotaRows;
  if (!quota?.allowed) {
    return json(res, 429, {
      error: 'Limite mensal atingido.',
      used: quota?.used ?? 30,
      remaining: 0,
      quota: 30
    });
  }

  const consultaId = quota.consulta_id;
  const key = process.env.SERPRO_CONSUMER_KEY;
  const secret = process.env.SERPRO_CONSUMER_SECRET;
  if (!key || !secret) {
    await markResult(userToken, consultaId, { status: 'falha_config', erro: 'Credenciais SERPRO não configuradas.' });
    return json(res, 503, {
      error: 'A integração SERPRO ainda não possui Consumer Key/Consumer Secret.',
      used: quota.used - 1,
      remaining: quota.remaining + 1,
      quota: 30
    });
  }

  try {
    const basic = Buffer.from(`${key}:${secret}`).toString('base64');
    const tokenRes = await fetch(TOKEN_URL, {
      method: 'POST',
      headers: {
        Authorization: `Basic ${basic}`,
        'Content-Type': 'application/x-www-form-urlencoded',
        Accept: 'application/json'
      },
      body: 'grant_type=client_credentials'
    });
    const tokenBody = await tokenRes.json().catch(() => ({}));
    if (!tokenRes.ok || !tokenBody.access_token) {
      await markResult(userToken, consultaId, { status: 'falha_config', http_status: tokenRes.status, erro: 'Falha ao autenticar no SERPRO.' });
      return json(res, 502, { error: 'Falha na autenticação com o SERPRO. Confira as credenciais.', serproStatus: tokenRes.status });
    }

    const baseUrl = (process.env.SERPRO_CNPJ_BASE_URL || DEFAULT_CNPJ_BASE).replace(/\/$/, '');
    const apiRes = await fetch(`${baseUrl}/${encodeURIComponent(cnpj)}`, {
      method: 'GET',
      headers: {
        Authorization: `Bearer ${tokenBody.access_token}`,
        Accept: 'application/json',
        'x-request-tag': `EMC-${Date.now()}`.slice(0, 32)
      }
    });
    const text = await apiRes.text();
    let data;
    try { data = JSON.parse(text); } catch { data = { raw: text }; }

    if (!apiRes.ok && apiRes.status !== 206) {
      await markResult(userToken, consultaId, {
        status: 'falha_api',
        http_status: apiRes.status,
        erro: data?.mensagem || data?.message || `SERPRO HTTP ${apiRes.status}`
      });
      return json(res, apiRes.status === 404 ? 404 : 502, {
        error: data?.mensagem || data?.message || 'A Consulta CNPJ do SERPRO não retornou sucesso.',
        serproStatus: apiRes.status,
        used: quota.used,
        remaining: quota.remaining,
        quota: 30
      });
    }

    await markResult(userToken, consultaId, {
      status: 'sucesso',
      http_status: apiRes.status,
      resposta_resumo: {
        ni: data?.ni || cnpj,
        nomeEmpresarial: data?.nomeEmpresarial || data?.nome || null,
        nomeFantasia: data?.nomeFantasia || null,
        situacaoCadastral: data?.situacaoCadastral || null
      },
      erro: null
    });

    return json(res, 200, {
      ok: true,
      data,
      quota: { used: quota.used, remaining: quota.remaining, limit: 30 }
    });
  } catch (err) {
    await markResult(userToken, consultaId, { status: 'falha_config', erro: String(err?.message || err) });
    return json(res, 502, { error: 'Falha de comunicação com o SERPRO.', detail: String(err?.message || err) });
  }
}

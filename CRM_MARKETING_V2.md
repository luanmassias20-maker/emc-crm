# EMC CRM Marketing — Arquitetura V2

## Decisão de produto
O CRM deixa de tentar substituir ferramentas especializadas de descoberta de CNPJ. A prospecção externa pode ser feita por ferramentas dedicadas; o EMC CRM passa a concentrar aquisição, marketing, atendimento, qualificação, conversão e pós-venda.

## Fluxo principal
Campanha → Lead → Atendimento → Qualificação → Proposta → Negociação → Conversão → Validação cadastral/SERPRO → Contrato → Cliente.

## Navegação
### Visão Geral
- Dashboard Executivo

### Marketing
- Central de Campanhas
- Meta Ads
- Google Ads
- Criativos
- Públicos

### CRM
- Leads
- Novo Lead Manual
- Funil Comercial
- Atividades
- Contatos
- Empresas

### Comunicação
- WhatsApp
- E-mail
- Modelos de mensagem

### Pós-conversão
- Clientes convertidos
- Validação SERPRO
- Contratos

### Inteligência
- Relatório de Marketing
- Relatório Comercial
- ROI / CAC / ROAS
- Agente IA de Marketing

### Sistema
- Integrações
- Configurações

## Dashboard
Indicadores prioritários:
- Investimento em mídia
- Leads recebidos
- CPL
- Leads qualificados
- Propostas enviadas
- Clientes convertidos
- Taxa de conversão
- Receita mensal contratada (MRR)
- CAC
- ROAS

Também deve existir visão por origem/campanha para descobrir qual mídia gera cliente, e não apenas lead barato.

## Lead
Cada lead deve registrar, quando disponível:
- nome
- empresa
- CNPJ
- telefone/WhatsApp
- e-mail
- cidade/UF
- serviço de interesse
- origem
- plataforma
- campanha
- conjunto/grupo de anúncios
- anúncio/criativo
- parâmetros UTM
- data de entrada
- responsável
- etapa do funil
- score
- mensalidade estimada
- próximo contato
- observações

Origens iniciais: Meta Ads, Google Ads, Manual, Indicação, WhatsApp, Instagram, Site e Prospecção externa.

## Lead manual
Manter tela/modal exclusiva, independente da captura automática. O usuário deve poder registrar o lead mesmo sem CNPJ.

## Funil
Etapas padrão:
1. Novo
2. Contato iniciado
3. Qualificado
4. Diagnóstico
5. Proposta enviada
6. Negociação
7. Convertido
8. Perdido

Registrar histórico de mudança de etapa para permitir métricas de conversão e tempo médio.

## Central de Campanhas
Cada campanha deve possuir:
- plataforma
- nome
- objetivo
- serviço
- região
- orçamento diário
- orçamento total
- início/fim
- status
- público
- criativo
- investimento
- impressões
- alcance
- cliques
- leads
- CPL
- qualificados
- propostas
- clientes
- receita contratada
- CAC
- ROAS

A interface deve permitir preparar campanhas no CRM. Publicação via API somente após aprovação humana explícita.

## Agente IA de Marketing
Funções planejadas:
- analisar campanhas
- comparar CPL e CAC
- priorizar conversão real em cliente
- detectar campanhas com desperdício
- sugerir redistribuição de orçamento
- sugerir público
- sugerir copy
- sugerir criativos
- gerar resumo executivo

A IA recomenda; alteração de orçamento, ativação ou publicação exige aprovação do usuário.

## Integrações
Fases planejadas:
1. Supabase — dados e autenticação
2. Meta — campanhas e leads
3. Google Ads — campanhas e métricas
4. WhatsApp — atendimento
5. SERPRO — somente pós-conversão/validação cadastral

Credenciais privadas nunca devem ficar expostas no frontend.

## Modelo de dados sugerido
- leads
- lead_stage_history
- activities
- contacts
- companies
- marketing_campaigns
- marketing_adsets
- marketing_ads
- marketing_daily_metrics
- marketing_creatives
- audiences
- integrations
- converted_clients
- serpro_queries
- contracts

## Regras de negócio
- Todo lead deve possuir origem.
- Leads vindos de Ads devem preservar IDs da plataforma e UTMs quando disponíveis.
- Evitar duplicação por telefone, e-mail e CNPJ.
- Conversão comercial deve retroalimentar os relatórios de campanha.
- CPL nunca será a única métrica de otimização.
- CAC, taxa de conversão e receita contratada têm prioridade na análise.
- SERPRO não é ferramenta de prospecção.

## Fases de implementação
### Fase 1 — Base funcional
Dashboard, leads, lead manual, funil, campanhas cadastradas manualmente e métricas.

### Fase 2 — Meta
Conectar conta, importar campanhas/métricas e capturar leads.

### Fase 3 — Inteligência
Agente IA e recomendações de otimização.

### Fase 4 — Google Ads
Importação e gerenciamento assistido.

### Fase 5 — Conversão
SERPRO, contratos e fechamento do ciclo comercial.

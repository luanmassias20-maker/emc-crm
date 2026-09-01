# Atualizador semanal da base CNPJ — EMC CRM

Este job roda toda segunda-feira e consulta a competência mais recente dos Dados Abertos do CNPJ da Receita Federal.
Se a competência já foi importada, termina sem baixar os arquivos grandes.

## Configuração no GitHub

Secrets obrigatórios:
- SUPABASE_URL = https://zcldskzmpsqsystlshlv.supabase.co
- SUPABASE_SERVICE_ROLE_KEY = chave service_role do projeto Supabase (NUNCA usar no frontend)

Variables recomendadas:
- RFB_UFS = PA
- RFB_RETENTION_DAYS = 180

O padrão foi deixado em PA + 180 dias para manter o banco enxuto.
É possível adicionar estados separados por vírgula, por exemplo: PA,MA,AP.

## O que o processo faz
1. Detecta a competência mensal mais recente da RFB.
2. Pula a carga se essa competência já estiver concluída.
3. Baixa e lê os arquivos oficiais em streaming/sequencialmente.
4. Mantém apenas estabelecimentos ATIVOS, nos estados configurados e dentro da janela de abertura.
5. Enriquece com razão social, porte, Simples/MEI, CNAE, município, telefone e e-mail.
6. Faz upsert em `public.receita_empresas`.
7. Atualiza `public.receita_import_status`.
8. Remove registros fora da janela de retenção configurada.

Observação: o identificador CNPJ é tratado como texto para suportar o padrão alfanumérico introduzido em 2026.

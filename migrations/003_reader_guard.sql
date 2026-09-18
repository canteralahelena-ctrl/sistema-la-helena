-- Defensa adicional para el rol que usará el conector ChatGPT.
ALTER ROLE helena_bridge_reader SET default_transaction_read_only = on;
REVOKE CREATE ON SCHEMA public FROM helena_bridge_reader;
REVOKE CREATE ON SCHEMA replica FROM helena_bridge_reader;

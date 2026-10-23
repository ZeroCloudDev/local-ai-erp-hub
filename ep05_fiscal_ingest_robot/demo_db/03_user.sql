-- =====================================================================
-- EP05 least-privilege account.
--
-- The password is NOT stored here. setup_demo_db.py creates the user
-- with the password from the EP05_DB_PASSWORD environment variable and
-- then runs these GRANT statements.
--
-- ep05_demo can only touch kasa_ep05, and only with SELECT/INSERT/UPDATE.
-- No DELETE, no DROP, no access to any other database.
-- Both 'localhost' and '127.0.0.1' are granted because a TCP connection
-- to 127.0.0.1 may be matched by either host entry.
-- =====================================================================
GRANT SELECT, INSERT, UPDATE ON kasa_ep05.* TO 'ep05_demo'@'localhost';
GRANT SELECT, INSERT, UPDATE ON kasa_ep05.* TO 'ep05_demo'@'127.0.0.1';
FLUSH PRIVILEGES;

-- =====================================================================
-- EP05 demo database: kasa_ep05
-- ---------------------------------------------------------------------
-- WHY THIS FILE EXISTS
--   The five POS tables below are copied *structure only* from the real
--   POS dump used for this episode (artikli, artcjenik, tarifa, jmjera,
--   artikli_grupe). Not a single original row is copied. The original
--   dump is never executed.
--
--   kasa_ep05 is an independent local test database. It proves that the
--   adapter writes into a real POS table layout; it does NOT prove how an
--   unknown live POS application will behave with these rows.
--
-- SAFETY
--   This script DROPS and recreates kasa_ep05 only. It is run by
--   setup_demo_db.py as a separate setup step, never inside processing:
--   CREATE/DROP/ALTER/TRUNCATE cause implicit commits in MariaDB/MySQL.
--
-- Compatible with MariaDB 10.4 (XAMPP) and newer.
-- =====================================================================

DROP DATABASE IF EXISTS kasa_ep05;
CREATE DATABASE kasa_ep05 CHARACTER SET utf8 COLLATE utf8_general_ci;
USE kasa_ep05;

-- ---------------------------------------------------------------------
-- Original POS structure (verbatim DDL from the supplied dump).
-- Note what the real structure does NOT enforce:
--   * artikli.art_broj has no UNIQUE key  -> the adapter must check duplicates.
--   * artcjenik has no unique key on (idart, cjnaziv, loc, pjs)
--                                          -> the adapter selects explicitly.
--   * artikli.jedmjer is text holding a jmjera.id ('1')
--                                          -> verify_demo rejects non-canonical text.
--   * artikli.cij is DECIMAL(18,4), artcjenik.cijena is DOUBLE
--                                          -> compared at 2 decimals.
-- ---------------------------------------------------------------------

CREATE TABLE `artcjenik` (
  `id` varchar(45) NOT NULL,
  `cijena` double NOT NULL DEFAULT '0',
  `loc` varchar(45) NOT NULL DEFAULT '0',
  `cjnaziv` varchar(45) NOT NULL,
  `br` int(10) unsigned NOT NULL DEFAULT '0',
  `upd` int(10) unsigned NOT NULL DEFAULT '0',
  `idart` varchar(45) NOT NULL,
  `deleted` int(4) unsigned NOT NULL DEFAULT '0',
  `sank` int(10) unsigned NOT NULL DEFAULT '0',
  `pjs` int(4) unsigned NOT NULL DEFAULT '1',
  PRIMARY KEY (`id`)
) ENGINE=InnoDB DEFAULT CHARSET=utf8;

CREATE TABLE `artikli` (
  `art_broj` int(11) DEFAULT '0',
  `naziv` varchar(50) DEFAULT ' ',
  `cij` decimal(18,4) DEFAULT '0.0000',
  `tarifa` int(11) DEFAULT '0',
  `sank` int(11) DEFAULT '0',
  `kuhinja` varchar(24) DEFAULT '00000000',
  `sl` int(11) DEFAULT '0',
  `alkohol` int(11) DEFAULT '0',
  `bezalkohol` text,
  `ulcijenabezpdv` double DEFAULT '0',
  `ulcijenasapdv` double DEFAULT '0',
  `minzalihe` decimal(10,0) DEFAULT '0',
  `maxzalihe` decimal(10,0) DEFAULT '0',
  `izcijenabezbdv` decimal(15,4) DEFAULT '0.0000',
  `izcijenasapdv` decimal(15,4) DEFAULT '0.0000',
  `jedmjer` varchar(50) DEFAULT '0',
  `tip` varchar(50) DEFAULT '0',
  `stanje` decimal(15,4) DEFAULT '0.0000',
  `m1` decimal(15,4) DEFAULT '0.0000',
  `m2` decimal(15,4) DEFAULT '0.0000',
  `m3` decimal(15,4) DEFAULT '0.0000',
  `m4` decimal(15,4) DEFAULT '0.0000',
  `m5` varchar(50) DEFAULT '0',
  `kasa` int(11) DEFAULT '0',
  `id` varchar(45) NOT NULL,
  `art_usl` int(11) DEFAULT '0',
  `nazivartikla` text,
  `cigarete` int(11) DEFAULT '0',
  `ostalo` int(11) DEFAULT '0',
  `grupa` int(11) DEFAULT '0',
  `ulaz` int(11) DEFAULT '0',
  `slika` varchar(50) DEFAULT '0',
  `sanklista` int(11) DEFAULT '0',
  `lokacija` smallint(6) DEFAULT '0',
  `prsank` int(11) DEFAULT '0',
  `dusl` smallint(6) DEFAULT '0',
  `bar` varchar(50) DEFAULT '0',
  `novo` int(11) DEFAULT '0',
  `unic` varchar(50) DEFAULT '0',
  `cod` varchar(50) DEFAULT '0',
  `code` varchar(50) DEFAULT '0',
  `deleted` int(4) DEFAULT '0',
  `idd` varchar(50) DEFAULT NULL,
  `upd` int(4) DEFAULT '0',
  `red` int(4) unsigned DEFAULT '0',
  PRIMARY KEY (`id`)
) ENGINE=InnoDB DEFAULT CHARSET=utf8;

CREATE TABLE `artikli_grupe` (
  `id` int(11) NOT NULL DEFAULT '0',
  `naziv` varchar(50) DEFAULT NULL,
  `idd` varchar(50) DEFAULT NULL,
  `deleted` int(4) DEFAULT '0',
  `upd` int(4) DEFAULT '0',
  `slika` varchar(50) DEFAULT NULL,
  PRIMARY KEY (`id`)
) ENGINE=InnoDB DEFAULT CHARSET=utf8;

CREATE TABLE `jmjera` (
  `id` int(10) unsigned NOT NULL AUTO_INCREMENT,
  `naziv` varchar(50) DEFAULT NULL,
  `nazivskr` varchar(30) DEFAULT NULL,
  `idd` varchar(50) DEFAULT NULL,
  `upd` int(4) DEFAULT '0',
  `deleted` int(4) DEFAULT '0',
  PRIMARY KEY (`id`)
) ENGINE=InnoDB DEFAULT CHARSET=utf8;

CREATE TABLE `tarifa` (
  `id` int(10) unsigned NOT NULL AUTO_INCREMENT,
  `porez` varchar(50) DEFAULT NULL,
  `iznos` decimal(10,2) DEFAULT NULL,
  `idd` varchar(50) DEFAULT NULL,
  `upd` int(4) DEFAULT '0',
  PRIMARY KEY (`id`)
) ENGINE=InnoDB DEFAULT CHARSET=utf8;

-- ---------------------------------------------------------------------
-- EP05 helper tables (ours, not part of the POS). All InnoDB so that
-- audit rows commit or roll back together with the POS rows.
-- ---------------------------------------------------------------------

-- One row per received document. UNIQUE(file_hash) is the replay guard:
-- the same bytes can never be written twice, whatever the file name.
CREATE TABLE `ep05_dokumenti` (
  `id` bigint unsigned NOT NULL AUTO_INCREMENT,
  `file_hash` char(64) NOT NULL,
  `file_name` varchar(255) NOT NULL,
  `source_path` varchar(1024) NOT NULL,
  `source_kind` varchar(16) NOT NULL,
  `profile_version` varchar(64) NOT NULL,
  `model_name` varchar(64) DEFAULT NULL,
  `status` varchar(32) NOT NULL,
  `items_total` int NOT NULL DEFAULT 0,
  `items_quarantined` int NOT NULL DEFAULT 0,
  `committed_at` datetime NOT NULL,
  `archived_path` varchar(1024) DEFAULT NULL,
  `archived_at` datetime DEFAULT NULL,
  `archive_attempts` int NOT NULL DEFAULT 0,
  PRIMARY KEY (`id`),
  UNIQUE KEY `uq_ep05_dokumenti_hash` (`file_hash`)
) ENGINE=InnoDB DEFAULT CHARSET=utf8;

-- One row per source occurrence of a SKU and its outcome.
-- locator + source_segment let anyone trace a POS row back to the exact
-- line / PDF cell row / OCR row it came from.
CREATE TABLE `ep05_stavke` (
  `id` bigint unsigned NOT NULL AUTO_INCREMENT,
  `doc_id` bigint unsigned NOT NULL,
  `locator` varchar(255) NOT NULL,
  `source_segment` text NOT NULL,
  `candidate_json` longtext NOT NULL,
  `field_sources_json` longtext NOT NULL,
  `outcome` varchar(16) NOT NULL,          -- INSERT / UPDATE / NO_CHANGE / QUARANTINE
  `reason` varchar(64) DEFAULT NULL,
  `art_broj` int DEFAULT NULL,
  `art_id` varchar(45) DEFAULT NULL,
  `old_price` decimal(18,4) DEFAULT NULL,
  `new_price` decimal(18,4) DEFAULT NULL,
  `value_source` varchar(24) DEFAULT NULL, -- where the PRICE came from
  `created_at` datetime NOT NULL,
  PRIMARY KEY (`id`),
  KEY `ix_ep05_stavke_art` (`art_broj`),
  CONSTRAINT `fk_ep05_stavke_doc` FOREIGN KEY (`doc_id`) REFERENCES `ep05_dokumenti` (`id`)
) ENGINE=InnoDB DEFAULT CHARSET=utf8;

-- Items held for an operator decision. Nothing here is in the POS tables.
CREATE TABLE `ep05_karantin` (
  `id` bigint unsigned NOT NULL AUTO_INCREMENT,
  `stavka_id` bigint unsigned NOT NULL,
  `art_broj` int DEFAULT NULL,
  `reason` varchar(64) NOT NULL,
  `detail` text,
  `status` varchar(16) NOT NULL DEFAULT 'OPEN',  -- OPEN / RESOLVED / REJECTED
  `operator_price` decimal(18,4) DEFAULT NULL,
  `operator_name` varchar(64) DEFAULT NULL,
  `operator_confirmation` varchar(255) DEFAULT NULL,
  `resolved_at` datetime DEFAULT NULL,
  `resolution_stavka_id` bigint unsigned DEFAULT NULL,
  PRIMARY KEY (`id`),
  KEY `ix_ep05_karantin_status` (`status`),
  CONSTRAINT `fk_ep05_karantin_stavka` FOREIGN KEY (`stavka_id`) REFERENCES `ep05_stavke` (`id`)
) ENGINE=InnoDB DEFAULT CHARSET=utf8;

-- Single-row mutex. Every writer (watch service, quarantine CLI, a second
-- service instance) does SELECT ... FOR UPDATE on this row first, so POS
-- writes are serialized across processes. Slow work (OCR, LLM) happens
-- BEFORE the lock is taken, so the lock is held only for short SQL work.
CREATE TABLE `ep05_writer_lock` (
  `id` tinyint unsigned NOT NULL,
  `holder` varchar(128) DEFAULT NULL,
  `acquired_at` datetime DEFAULT NULL,
  PRIMARY KEY (`id`)
) ENGINE=InnoDB DEFAULT CHARSET=utf8;

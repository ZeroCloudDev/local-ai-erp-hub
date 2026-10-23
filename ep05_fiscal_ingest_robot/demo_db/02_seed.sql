-- =====================================================================
-- EP05 seed: "Maple Street Market" (a FICTIONAL US store).
-- All data is synthetic. Nothing here comes from the original POS dump.
--
-- Price semantics in THIS test database (decision D1):
--   artikli.cij and the selected artcjenik row hold the USD shelf price
--   BEFORE sales tax. The tax class is a separate reference (tarifa).
--   This is a rule of our test database, not a claim about how the
--   original POS uses cij.
--
-- tarifa.iznos 8.25 is an INVENTED demo rate. It is not presented as the
-- real sales tax rate of any state or city.
--
-- sank / kasa / grupa / upd / idd are explicit TEST values (also listed in
-- pos_adapter_config.example.toml), not confirmed settings of a real POS.
-- Fixed UUIDs keep the seed byte-for-byte reproducible.
-- =====================================================================
USE kasa_ep05;

START TRANSACTION;

INSERT INTO tarifa (id, porez, iznos, idd, upd) VALUES
  (1, 'T', 8.25, 'ep05-seed', 2),   -- taxable, invented demo rate
  (2, 'E', 0.00, 'ep05-seed', 2);   -- exempt

INSERT INTO jmjera (id, naziv, nazivskr, idd, upd, deleted) VALUES
  (1, 'Each',   'EA',  'ep05-seed', 2, 0),
  (2, 'Pound',  'LB',  'ep05-seed', 2, 0),
  (3, 'Gallon', 'GAL', 'ep05-seed', 2, 0);

INSERT INTO artikli_grupe (id, naziv, idd, deleted, upd, slika) VALUES
  (1, 'Grocery (EP05 demo)', 'ep05-seed', 0, 2, NULL);

-- jedmjer stores jmjera.id as canonical text ('1'), exactly like the real structure.
-- 95002 Cane Sugar 4 lb is a packaged item sold per EACH, not weighed per pound.
INSERT INTO artikli (art_broj, naziv, cij, tarifa, jedmjer, id, sank, kasa, grupa, upd, idd, deleted) VALUES
  (95001, 'Espresso Beans 1 lb',    12.99, 1, '1', '00000000-0e05-4000-8000-000000095001', 1, 0, 1, 2, 'ep05-seed', 0),
  (95002, 'Cane Sugar 4 lb',         4.49, 2, '1', '00000000-0e05-4000-8000-000000095002', 1, 0, 1, 2, 'ep05-seed', 0),
  (95003, 'Paper Cups 12 oz 50 ct',  6.99, 1, '1', '00000000-0e05-4000-8000-000000095003', 1, 0, 1, 2, 'ep05-seed', 0),
  (95004, 'Bottled Water 16.9 oz',   1.29, 1, '1', '00000000-0e05-4000-8000-000000095004', 1, 0, 1, 2, 'ep05-seed', 0),
  (95005, 'Whole Milk 1 gal',        4.19, 2, '1', '00000000-0e05-4000-8000-000000095005', 1, 0, 1, 2, 'ep05-seed', 0);

-- Exactly one OSNOVNI price-list row per article (cjnaziv='OSNOVNI', loc='0', pjs=1, deleted=0).
INSERT INTO artcjenik (id, cijena, loc, cjnaziv, br, upd, idart, deleted, sank, pjs) VALUES
  ('00000000-0e05-4000-9000-000000095001', 12.99, '0', 'OSNOVNI', 1, 2, '00000000-0e05-4000-8000-000000095001', 0, 1, 1),
  ('00000000-0e05-4000-9000-000000095002',  4.49, '0', 'OSNOVNI', 1, 2, '00000000-0e05-4000-8000-000000095002', 0, 1, 1),
  ('00000000-0e05-4000-9000-000000095003',  6.99, '0', 'OSNOVNI', 1, 2, '00000000-0e05-4000-8000-000000095003', 0, 1, 1),
  ('00000000-0e05-4000-9000-000000095004',  1.29, '0', 'OSNOVNI', 1, 2, '00000000-0e05-4000-8000-000000095004', 0, 1, 1),
  ('00000000-0e05-4000-9000-000000095005',  4.19, '0', 'OSNOVNI', 1, 2, '00000000-0e05-4000-8000-000000095005', 0, 1, 1);

-- The single mutex row used by all writers.
INSERT INTO ep05_writer_lock (id, holder, acquired_at) VALUES (1, NULL, NULL);

COMMIT;

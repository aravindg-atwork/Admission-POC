INSERT INTO projects (id, name, created_at)
VALUES
  ('bfsc', 'B.F.Sc.', NOW()),
  ('btech-dairy', 'B.Tech. (Dairy Technology)', NOW())
ON CONFLICT (id) DO UPDATE SET name = EXCLUDED.name;

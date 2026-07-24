using System;
using System.Collections.Generic;
using System.IO;
using System.Linq;
using System.Security.Cryptography;
using Newtonsoft.Json;

namespace AdmissionAssistant.Core.Security
{
    // Every consumer of the chat/ingest API - the admission site's own chat widget,
    // the future browser extension, any other integration - gets its own key, so any
    // one of them can be revoked independently without a code change or affecting the
    // others. One stable URL, many toggleable keys, instead of a URL per consumer.
    public class ApiKeyStore
    {
        private readonly string _filePath;
        private readonly object _lock = new object();

        public ApiKeyStore(string filePath)
        {
            _filePath = filePath;
        }

        public List<ApiKey> List()
        {
            lock (_lock)
            {
                return Load();
            }
        }

        public ApiKey Create(string label)
        {
            lock (_lock)
            {
                var keys = Load();
                var entry = new ApiKey
                {
                    Id = GenerateId(),
                    Key = "aas_" + GenerateSecret(),
                    Label = string.IsNullOrWhiteSpace(label) ? "unlabeled" : label,
                    Active = true,
                    CreatedAt = DateTime.UtcNow
                };
                keys.Add(entry);
                Save(keys);
                return entry;
            }
        }

        public ApiKey SetActive(string id, bool active)
        {
            lock (_lock)
            {
                var keys = Load();
                var entry = keys.FirstOrDefault(k => k.Id == id);
                if (entry == null) return null;

                entry.Active = active;
                Save(keys);
                return entry;
            }
        }

        public bool Delete(string id)
        {
            lock (_lock)
            {
                var keys = Load();
                var removed = keys.RemoveAll(k => k.Id == id);
                if (removed == 0) return false;

                Save(keys);
                return true;
            }
        }

        public bool IsActive(string keyValue)
        {
            if (string.IsNullOrEmpty(keyValue)) return false;

            lock (_lock)
            {
                return Load().Any(k => k.Key == keyValue && k.Active);
            }
        }

        // Auto-provisions a single always-on key for the admission site's own
        // first-party chat widget, distinct from keys issued to other consumers.
        public ApiKey GetOrCreateDefault(string label)
        {
            lock (_lock)
            {
                var keys = Load();
                var existing = keys.FirstOrDefault(k => k.Label == label);
                if (existing != null) return existing;

                var entry = new ApiKey
                {
                    Id = GenerateId(),
                    Key = "aas_" + GenerateSecret(),
                    Label = label,
                    Active = true,
                    CreatedAt = DateTime.UtcNow
                };
                keys.Add(entry);
                Save(keys);
                return entry;
            }
        }

        private List<ApiKey> Load()
        {
            if (!File.Exists(_filePath)) return new List<ApiKey>();
            var json = File.ReadAllText(_filePath);
            return string.IsNullOrWhiteSpace(json)
                ? new List<ApiKey>()
                : JsonConvert.DeserializeObject<List<ApiKey>>(json) ?? new List<ApiKey>();
        }

        private void Save(List<ApiKey> keys)
        {
            var dir = Path.GetDirectoryName(_filePath);
            if (!string.IsNullOrEmpty(dir) && !Directory.Exists(dir))
                Directory.CreateDirectory(dir);

            File.WriteAllText(_filePath, JsonConvert.SerializeObject(keys, Formatting.Indented));
        }

        private static string GenerateId()
        {
            var bytes = new byte[6];
            using (var rng = RandomNumberGenerator.Create())
                rng.GetBytes(bytes);
            return BitConverter.ToString(bytes).Replace("-", "").ToLowerInvariant();
        }

        private static string GenerateSecret()
        {
            var bytes = new byte[32];
            using (var rng = RandomNumberGenerator.Create())
                rng.GetBytes(bytes);
            return Convert.ToBase64String(bytes).Replace("+", "").Replace("/", "").Replace("=", "");
        }
    }
}

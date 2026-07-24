using System;

namespace AdmissionAssistant.Core.Security
{
    public class ApiKey
    {
        public string Id { get; set; }
        public string Key { get; set; }
        public string Label { get; set; }
        public bool Active { get; set; }
        public DateTime CreatedAt { get; set; }
    }
}

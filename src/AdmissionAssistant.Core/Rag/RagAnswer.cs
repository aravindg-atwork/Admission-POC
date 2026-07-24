using System.Collections.Generic;

namespace AdmissionAssistant.Core.Rag
{
    public class RagAnswer
    {
        public string AnswerText { get; set; }
        public List<int> PageReferences { get; set; }
    }
}

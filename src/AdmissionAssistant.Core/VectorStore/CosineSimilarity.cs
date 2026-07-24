using System;

namespace AdmissionAssistant.Core.VectorStore
{
    public static class CosineSimilarity
    {
        public static float Compute(float[] a, float[] b)
        {
            float dot = 0, normA = 0, normB = 0;

            for (var i = 0; i < a.Length; i++)
            {
                dot += a[i] * b[i];
                normA += a[i] * a[i];
                normB += b[i] * b[i];
            }

            if (normA == 0 || normB == 0) return 0f;
            return (float)(dot / (Math.Sqrt(normA) * Math.Sqrt(normB)));
        }
    }
}

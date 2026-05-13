/**
 * 描述: 向量相似度工具
 * 主要功能:
 *     - 计算两个 embedding 向量的 cosine similarity
 *     - 对空向量、维度不一致和非有限数值返回安全结果
 */

export function cosineSimilarity(a: readonly number[], b: readonly number[]): number {
  if (a.length !== b.length || a.length === 0) {
    return 0;
  }

  let dot = 0;
  let aMagnitude = 0;
  let bMagnitude = 0;

  for (let index = 0; index < a.length; index += 1) {
    const aValue = a[index] ?? 0;
    const bValue = b[index] ?? 0;

    if (!Number.isFinite(aValue) || !Number.isFinite(bValue)) {
      return 0;
    }

    dot += aValue * bValue;
    aMagnitude += aValue * aValue;
    bMagnitude += bValue * bValue;
  }

  if (aMagnitude === 0 || bMagnitude === 0) {
    return 0;
  }

  return dot / (Math.sqrt(aMagnitude) * Math.sqrt(bMagnitude));
}

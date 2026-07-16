const STAKEHOLDER_TYPE_ORDER: Record<string, number> = {
  primary_user: 0,
  system_owner: 1,
  external_party: 2,
};

function stakeholderTypeOrder(value: unknown) {
  const key = String(value ?? "").trim();
  return STAKEHOLDER_TYPE_ORDER[key] ?? 99;
}

export function stakeholderTypeLabel(value: string) {
  switch (value) {
    case "primary_user":
      return "核心使用者";
    case "system_owner":
      return "系統所有者與管理者";
    case "external_party":
      return "外部相關單位";
    default:
      return value;
  }
}

export function sortStakeholdersByType<T>(
  rows: T[],
  getType: (row: T) => unknown,
) {
  return rows
    .map((row, index) => ({ row, index }))
    .sort((left, right) => {
      const typeDiff = stakeholderTypeOrder(getType(left.row)) - stakeholderTypeOrder(getType(right.row));
      if (typeDiff !== 0) return typeDiff;
      return left.index - right.index;
    })
    .map((item) => item.row);
}

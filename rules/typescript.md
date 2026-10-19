# Python to Strict TypeScript Translation Rules

## 1. Compiler & Linter Target
All generated TypeScript files must compile cleanly under:
- `tsc --noEmit --strict` (TypeScript 5+ / 7+)
- Target: `ES2022`, Module: `ESNext`, ModuleResolution: `bundler`
- Zero `any` types (`noImplicitAny: true`, `strictNullChecks: true`)

## 2. Type Mapping
| Python Type | TypeScript Type |
|---|---|
| `int`, `float` | `number` |
| `str` | `string` |
| `bool` | `boolean` |
| `None` | `null` or `void` (for return types) |
| `list[T]` | `Array<T>` or `T[]` |
| `dict[K, V]` | `Record<K, V>` |
| `tuple[A, B]` | `[A, B]` |
| `Optional[T]` / `T \| None` | `T \| null` |
| `@dataclass` / `TypedDict` | `export interface ...` |

## 3. Semantics & Idioms
1. **Explicit Exports:** Export all public functions, interfaces, and constants with `export`.
2. **Equality:** Always use `===` and `!==`.
3. **Integer Division:** Translate Python `a // b` to `Math.floor(a / b)`.
4. **Rounding:** Ensure deterministic decimal rounding via `Math.round((value + Number.EPSILON) * 10**n) / 10**n`.
5. **Dictionary Access:** Translate `d.get(k, default)` to `(d[k] ?? default)`.
6. **Exceptions:** Translate `raise ValueError(msg)` to `throw new Error(msg)`.

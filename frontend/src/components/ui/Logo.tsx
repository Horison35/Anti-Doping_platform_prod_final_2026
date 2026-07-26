// Знак платформы: щит (контроль/арбитраж) + апертура радара (машинное наблюдение) —
// геометрия вместо иконки-заглушки. Единая отрисовка на любом размере (наврайд, экран
// пароля, сплэш), поэтому вынесена в общий компонент, а не продублирована по месту.
export function Logo({ size = 28 }: { size?: number }) {
  const gradId = "logoGrad"
  return (
    <svg width={size} height={size} viewBox="0 0 48 48" fill="none" aria-hidden="true">
      <defs>
        <linearGradient id={gradId} x1="4" y1="4" x2="44" y2="44" gradientUnits="userSpaceOnUse">
          <stop offset="0" stopColor="#6ea8ff" />
          <stop offset="1" stopColor="#8a5cf6" />
        </linearGradient>
      </defs>
      <path
        d="M24 3.2 L41.5 9.6 V22.8 C41.5 33.8 34.2 41.4 24 44.8 C13.8 41.4 6.5 33.8 6.5 22.8 V9.6 Z"
        fill={`url(#${gradId})`}
        fillOpacity="0.14"
        stroke={`url(#${gradId})`}
        strokeWidth="1.8"
      />
      <g>
        <circle cx="24" cy="21.5" r="8.4" stroke={`url(#${gradId})`} strokeWidth="1.5" />
        <circle cx="24" cy="21.5" r="2.8" fill={`url(#${gradId})`} />
        <line x1="24" y1="9.6" x2="24" y2="13" stroke={`url(#${gradId})`} strokeWidth="1.5" strokeLinecap="round" />
        <line x1="24" y1="30" x2="24" y2="33.4" stroke={`url(#${gradId})`} strokeWidth="1.5" strokeLinecap="round" opacity="0.55" />
        <line x1="12.1" y1="21.5" x2="15.5" y2="21.5" stroke={`url(#${gradId})`} strokeWidth="1.5" strokeLinecap="round" opacity="0.7" />
        <line x1="32.5" y1="21.5" x2="35.9" y2="21.5" stroke={`url(#${gradId})`} strokeWidth="1.5" strokeLinecap="round" opacity="0.7" />
      </g>
    </svg>
  )
}

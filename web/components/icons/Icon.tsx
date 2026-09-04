type IconProps = {
  name: string;
  filled?: boolean;
  className?: string;
  size?: number;
};

export function Icon({ name, filled = false, className = "", size = 18 }: IconProps) {
  return (
    <span
      className={`material-symbols-outlined ${filled ? "fill" : ""} ${className}`}
      style={{ fontSize: size }}
      aria-hidden
    >
      {name}
    </span>
  );
}

import { Icon } from "../icons/Icon";

export function StarRating({ value }: { value: number | null }) {
  const rounded = value === null ? 0 : Math.round(value);
  return (
    <span className="inline-flex items-center text-gold" aria-label={value === null ? "no rating" : `${value} stars`}>
      {[1, 2, 3, 4, 5].map((star) => (
        <Icon
          key={star}
          name="star"
          filled={star <= rounded}
          size={14}
          className={star <= rounded ? "text-gold" : "text-line"}
        />
      ))}
    </span>
  );
}

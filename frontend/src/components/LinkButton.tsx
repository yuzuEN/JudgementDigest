import type { VariantProps } from "class-variance-authority";
import type { ComponentProps } from "react";
import { Link } from "react-router-dom";
import { cn } from "@/lib/utils";
import { buttonVariants } from "@/components/ui/button";

type Props = VariantProps<typeof buttonVariants> & Omit<ComponentProps<"a">, "href"> & ({ to: string; href?: never } | { href: string; to?: never });

/** 長得像按鈕的連結：換頁要用連結（role=link），不是按鈕。 */
export function LinkButton({ to, href, variant, size, className, ...props }: Props) {
  const cls = cn(buttonVariants({ variant, size }), "no-underline", className);
  return to !== undefined
    ? <Link data-slot="button" to={to} className={cls} {...props} />
    : <a data-slot="button" href={href} className={cls} {...props} />;
}

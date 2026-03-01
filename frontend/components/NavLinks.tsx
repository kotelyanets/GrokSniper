"use client";

import Link from "next/link";
import { usePathname } from "next/navigation";

const NAV_ITEMS = [
    { label: "Dashboard", href: "/" },
    { label: "Trades", href: "/trades" },
    { label: "Analysis", href: "/analysis" },
    { label: "Analytics", href: "/analytics" },
    { label: "Settings", href: "/settings" },
];

export default function NavLinks() {
    const pathname = usePathname();

    return (
        <nav className="hidden md:flex items-center gap-1">
            {NAV_ITEMS.map(({ label, href }) => {
                const isActive =
                    href === "/" ? pathname === "/" : pathname.startsWith(href);
                return (
                    <Link
                        key={href}
                        href={href}
                        className={`px-4 py-2 rounded-lg text-sm font-medium transition-all duration-150 ${isActive
                            ? "bg-gray-800/90 text-white border border-gray-700/50 shadow-sm"
                            : "text-gray-400 hover:text-white hover:bg-gray-800/50"
                            }`}
                    >
                        {label}
                    </Link>
                );
            })}
        </nav>
    );
}

import type { CapabilityKey, Role, UserOut } from "./types";

export type NavItem = { href: string; labelKey: string; capability?: CapabilityKey };

export type Portal = {
  slug: "admin" | "facility" | "coordinator" | "carrier";
  role: Role;
  name: string;
  audience: string;
  blurb: string;
  nav: NavItem[];
};

export const portals: Portal[] = [
  {
    slug: "admin",
    role: "admin",
    name: "Admin",
    audience: "Head office",
    blurb: "Facilities, carriers, users, shipments, AI management and audit.",
    nav: [
      { href: "/admin", labelKey: "nav.dashboard", capability: "analytics" },
      { href: "/admin/facilities", labelKey: "nav.facilities", capability: "manage_master" },
      { href: "/admin/carriers", labelKey: "nav.carriers", capability: "manage_master" },
      { href: "/admin/users", labelKey: "nav.users", capability: "manage_master" },
      { href: "/admin/drivers", labelKey: "nav.drivers", capability: "drivers_vehicles" },
      { href: "/admin/shipments", labelKey: "nav.shipments", capability: "shipments_write" },
      { href: "/admin/ai", labelKey: "nav.ai", capability: "ai_management" },
      { href: "/admin/audit", labelKey: "nav.audit", capability: "audit_log" },
      { href: "/admin/settings", labelKey: "nav.settings", capability: "system_settings" },
    ],
  },
  {
    slug: "facility",
    role: "facility_planner",
    name: "Facility",
    audience: "Warehouse planners",
    blurb: "Day schedule grid, docks, slots, dock events, yard and gate.",
    nav: [
      { href: "/facility", labelKey: "nav.home" },
      { href: "/facility/schedule", labelKey: "nav.schedule", capability: "day_schedule" },
      { href: "/facility/docks", labelKey: "nav.docks", capability: "docks_slots_rules" },
      { href: "/facility/yard", labelKey: "nav.yard", capability: "day_schedule" },
    ],
  },
  {
    slug: "coordinator",
    role: "coordinator",
    name: "Coordinator",
    audience: "Operations desk",
    blurb: "Live inbox of driver requests, decisions, escalations, takeover.",
    nav: [
      { href: "/coordinator", labelKey: "nav.inbox", capability: "booking_decisions" },
      { href: "/coordinator/holds", labelKey: "nav.holds", capability: "booking_decisions" },
      { href: "/coordinator/escalations", labelKey: "nav.escalations", capability: "escalations_takeover" },
      { href: "/coordinator/board", labelKey: "nav.board", capability: "day_schedule" },
    ],
  },
  {
    slug: "carrier",
    role: "carrier_user",
    name: "Carrier",
    audience: "Transport companies",
    blurb: "Assign drivers and vehicles, track shipments and slot changes.",
    nav: [
      { href: "/carrier", labelKey: "nav.dashboard" },
      { href: "/carrier/shipments", labelKey: "nav.incoming", capability: "shipment_details" },
      { href: "/carrier/drivers", labelKey: "nav.drivers", capability: "drivers_vehicles" },
      { href: "/carrier/vehicles", labelKey: "nav.vehicles", capability: "drivers_vehicles" },
    ],
  },
];

export function filterNav(nav: NavItem[], user: Pick<UserOut, "capabilities">): NavItem[] {
  return nav.filter((n) => !n.capability || Boolean(user.capabilities[n.capability]));
}

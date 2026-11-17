export type Portal = {
  slug: "admin" | "facility" | "coordinator" | "carrier";
  name: string;
  audience: string;
  blurb: string;
  nav: { href: string; label: string }[];
};

export const portals: Portal[] = [
  {
    slug: "admin",
    name: "Admin",
    audience: "Head office",
    blurb: "Facilities, carriers, users, shipments, AI management and audit.",
    nav: [
      { href: "/admin", label: "Network dashboard" },
      { href: "/admin/facilities", label: "Facilities" },
      { href: "/admin/carriers", label: "Carriers" },
      { href: "/admin/shipments", label: "Shipments" },
      { href: "/admin/ai", label: "AI management" },
      { href: "/admin/audit", label: "Audit log" },
    ],
  },
  {
    slug: "facility",
    name: "Facility",
    audience: "Warehouse planners",
    blurb: "Day schedule grid, docks, slots, dock events, yard and gate.",
    nav: [
      { href: "/facility", label: "Home" },
      { href: "/facility/schedule", label: "Day schedule" },
      { href: "/facility/docks", label: "Docks" },
      { href: "/facility/yard", label: "Yard and gate" },
    ],
  },
  {
    slug: "coordinator",
    name: "Coordinator",
    audience: "Operations desk",
    blurb: "Live inbox of driver requests, decisions, escalations, takeover.",
    nav: [
      { href: "/coordinator", label: "Inbox" },
      { href: "/coordinator/holds", label: "Holds" },
      { href: "/coordinator/escalations", label: "Escalations" },
      { href: "/coordinator/board", label: "Live board" },
    ],
  },
  {
    slug: "carrier",
    name: "Carrier",
    audience: "Transport companies",
    blurb: "Assign drivers and vehicles, track shipments and slot changes.",
    nav: [
      { href: "/carrier", label: "Dashboard" },
      { href: "/carrier/shipments", label: "Incoming shipments" },
      { href: "/carrier/drivers", label: "Drivers" },
      { href: "/carrier/vehicles", label: "Vehicles" },
    ],
  },
];

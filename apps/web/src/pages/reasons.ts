// What each review reason means for the planner.
export const REASONS: Record<string, string> = {
  outside_network: "No street near enough",
  ambiguous_street: "About as near one street as another",
  side_undetermined: "On the centre line; side of street unclear",
  wrong_side_of_one_way: "On the left of a one-way street",
  address_not_found: "Address not found",
  address_ambiguous: "Address matches more than one place",
  address_inexact: "Address found only after correcting it",
};

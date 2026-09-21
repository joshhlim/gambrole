// Mirrors api/app/friends_service.py and users_service.py. Note the absence
// of email on UserProfile: the API never discloses one.

export interface UserProfile {
  user_id: string;
  display_name: string;
  username: string | null;
}

/** Your own profile also carries the address on file, for Settings. */
export interface MyProfile extends UserProfile {
  email: string | null;
}

/** A friendship or pending request. `user` is always the other person. */
export interface FriendEdge {
  id: string;
  user: UserProfile;
  created_at: string;
}

export interface FriendsResponse {
  friends: FriendEdge[];
  incoming: FriendEdge[];
  outgoing: FriendEdge[];
}

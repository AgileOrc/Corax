import { createContext, useContext } from "react";

// {user, signIn(token, user), signOut(message)}, provided by App
export const SessionContext = createContext(null);
export const useSession = () => useContext(SessionContext);

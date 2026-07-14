import apiClient from "./client";


export async function login(username: string, password: string) {
  const form = new URLSearchParams();
  form.append("username", username);
  form.append("password", password);
  const response = await apiClient.post("/auth/login", form, {
    headers: { "Content-Type": "application/x-www-form-urlencoded" },
  });
  return response.data;
}

import { createRouter, createWebHistory } from "vue-router";

import HomeView from "@/views/HomeView.vue";

export const router = createRouter({
  history: createWebHistory(),
  routes: [
    { path: "/", name: "home", component: HomeView, meta: { title: "Projects" } },
    { path: "/admin", name: "admin", component: () => import("@/views/AdminView.vue"), meta: { title: "Admin" } },
    {
      path: "/projects/:project([A-Za-z0-9_-]{1,64})",
      component: () => import("@/views/ProjectView.vue"),
      props: true,
      children: [
        { path: "", redirect: (to) => ({ name: "ask", params: to.params }) },
        {
          // Without a conversation, the first question starts one.
          path: "ask/:conversation([0-9a-fA-F-]{36})?",
          name: "ask",
          component: () => import("@/views/project/AskView.vue"),
          meta: { title: "Ask" },
        },
        {
          path: "documents",
          name: "documents",
          component: () => import("@/views/project/DocumentsView.vue"),
          meta: { title: "Documents" },
        },
        {
          path: "search",
          name: "search",
          component: () => import("@/views/project/SearchView.vue"),
          meta: { title: "Search" },
        },
        {
          path: "assistant",
          name: "assistant",
          component: () => import("@/views/project/AssistantView.vue"),
          meta: { title: "Assistant" },
        },
        {
          path: "widget",
          name: "widget",
          component: () => import("@/views/project/WidgetView.vue"),
          meta: { title: "Chat widget" },
        },
        {
          path: "webhooks",
          name: "webhooks",
          component: () => import("@/views/project/WebhooksView.vue"),
          meta: { title: "Webhooks" },
        },
        {
          path: "usage",
          name: "usage",
          component: () => import("@/views/project/UsageView.vue"),
          meta: { title: "Usage" },
        },
      ],
    },
    {
      path: "/:path(.*)*",
      name: "not-found",
      component: () => import("@/views/NotFoundView.vue"),
      meta: { title: "Not found" },
    },
  ],
});

router.afterEach((to) => {
  const project = typeof to.params.project === "string" ? to.params.project : null;
  const parts = [to.meta.title as string | undefined, project, "Mini RAG"].filter(Boolean);
  document.title = parts.join(" · ");
});

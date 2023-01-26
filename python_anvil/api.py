from logging import getLogger
from typing import Any, AnyStr, Callable, Dict, List, Optional, Text, Tuple, Union

from .api_resources.mutations import *
from .api_resources.payload import (
    CreateEtchPacketPayload,
    FillPDFPayload,
    ForgeSubmitPayload,
    GeneratePDFPayload,
)
from .api_resources.requests import GraphqlRequest, PlainRequest, RestRequest
from .http import HTTPClient
from .multipart_helpers import get_multipart_payload


logger = getLogger(__name__)


def _get_return(res: Dict, get_data: Callable[[Dict], Union[Dict, List]]):
    """Process response and get data from path if provided."""
    _res = res
    if "response" in res and "headers" in res:
        _res = res["response"]
        return {"response": get_data(_res), "headers": res["headers"]}
    return get_data(_res)


class Anvil:
    """Main Anvil API class.

    Handles all GraphQL and REST queries.

    Usage:
        >> anvil = Anvil(api_key="my_key")
        >> payload = {}
        >> pdf_data = anvil.fill_pdf("the_template_id", payload)
    """

    # Version number to use for latest versions (usually drafts)
    VERSION_LATEST = -1
    # Version number to use for the latest published version.
    # This is the default when a version is not provided.
    VERSION_LATEST_PUBLISHED = -2

    def __init__(self, api_key=None, environment='dev'):
        self.client = HTTPClient(api_key=api_key, environment=environment)

    def query(
        self,
        query: str,
        variables: Union[Optional[Text], Dict[Text, Any]] = None,
        **kwargs,
    ):
        gql = GraphqlRequest(client=self.client)
        return gql.post(query, variables=variables, **kwargs)

    def mutate(self, query: BaseQuery, variables: dict, **kwargs):
        gql = GraphqlRequest(client=self.client)
        return gql.post(query.get_mutation(), variables, **kwargs)

    def mutate_multipart(self, files: Dict, **kwargs):
        """
        Multipart version of `mutate`.

        This will send a mutation based on the multipart spec defined here:
        https://github.com/jaydenseric/graphql-multipart-request-spec

        Note that `variables` and `query` have been removed and replaced with
        `files`. The entire GraphQL payload should already be prepared as a
        `dict` beforehand.

        :param files:
        :param kwargs:
        :return:
        """
        gql = GraphqlRequest(client=self.client)
        return gql.post_multipart(files=files, **kwargs)

    def request_rest(self, options: Optional[dict] = None):
        api = RestRequest(self.client, options=options)
        return api

    def fill_pdf(
        self, template_id: str, payload: Union[dict, AnyStr, FillPDFPayload], **kwargs
    ):
        """Fill an existing template with provided payload data.

        Use the casts graphql query to get a list of available templates you
        can use for this request.

        :param template_id: eid of an existing template/cast
        :type template_id: str
        :param payload: payload in the form of a dict or JSON data
        :type payload: dict|str
        :param kwargs.version_number: specific template version number to use. If
            not provided, the latest _published_ version will be used.
        :type kwargs.version_number: int
        """
        try:
            if isinstance(payload, dict):
                data = FillPDFPayload(**payload)
            elif isinstance(payload, str):
                data = FillPDFPayload.parse_raw(
                    payload, content_type="application/json"
                )
            elif isinstance(payload, FillPDFPayload):
                data = payload
            else:
                raise ValueError("`payload` must be a valid JSON string or a dict")
        except KeyError as e:
            logger.exception(e)
            raise ValueError(
                "`payload` validation failed. Please make sure all required "
                "fields are set. "
            ) from e

        version_number = kwargs.pop("version_number", None)
        if version_number:
            kwargs["params"] = dict(versionNumber=version_number)

        api = RestRequest(client=self.client)
        return api.post(
            f"fill/{template_id}.pdf",
            data.dict(by_alias=True, exclude_none=True) if data else {},
            **kwargs,
        )

    def generate_pdf(self, payload: Union[AnyStr, Dict, GeneratePDFPayload], **kwargs):
        if not payload:
            raise ValueError("`payload` must be a valid JSON string or a dict")

        if isinstance(payload, dict):
            data = GeneratePDFPayload(**payload)
        elif isinstance(payload, str):
            data = GeneratePDFPayload.parse_raw(
                payload, content_type="application/json"
            )
        elif isinstance(payload, GeneratePDFPayload):
            data = payload
        else:
            raise ValueError("`payload` must be a valid JSON string or a dict")

        # Any data errors would come from here
        api = RestRequest(client=self.client)
        return api.post(
            "generate-pdf", data=data.dict(by_alias=True, exclude_none=True), **kwargs
        )

    def get_cast(
        self,
        eid: str,
        fields: Optional[List[str]] = None,
        version_number: Optional[int] = None,
        cast_args: Optional[List[Tuple[str, str]]] = None,
        **kwargs,
    ) -> Dict[str, Any]:

        if not fields:
            # Use default fields
            fields = ["eid", "title", "fieldInfo"]

        if not cast_args:
            cast_args = []

        cast_args.append(("eid", f'"{eid}"'))

        # If `version_number` isn't provided, the API will default to the
        # latest published version.
        if version_number:
            cast_args.append(("versionNumber", str(version_number)))

        arg_str = ""
        if len(cast_args):
            joined_args = [(":".join(arg)) for arg in cast_args]
            arg_str = f"({','.join(joined_args)})"

        res = self.query(
            f"""{{
              cast {arg_str} {{
                {" ".join(fields)}
              }}
            }}""",
            **kwargs,
        )

        def get_data(r) -> Dict[str, Any]:
            return r["data"]["cast"]

        return _get_return(res, get_data=get_data)

    def get_casts(self, fields=None, show_all=False, **kwargs) -> List[Dict[str, Any]]:
        if not fields:
            # Use default fields
            fields = ["eid", "title", "fieldInfo"]

        cast_args = "" if show_all else "(isTemplate: true)"

        res = self.query(
            f"""{{
              currentUser {{
                organizations {{
                  casts {cast_args} {{
                    {" ".join(fields)}
                  }}
                }}
              }}
            }}""",
            **kwargs,
        )

        def get_data(r):
            orgs = r["data"]["currentUser"]["organizations"]
            return [item for org in orgs for item in org["casts"]]

        return _get_return(res, get_data=get_data)

    def get_current_user(self, **kwargs):
        res = self.query(
            """{
              currentUser {
                name
                email
                eid
                role
                organizations {
                  eid
                  name
                  slug
                  casts {
                    eid
                    name
                  }
                }
              }
            }
            """,
            **kwargs,
        )

        return _get_return(res, get_data=lambda r: r["data"]["currentUser"])

    def get_welds(self, **kwargs) -> Union[List, Tuple[List, Dict]]:
        res = self.query(
            """{
              currentUser {
                organizations {
                  welds {
                    eid
                    slug
                    title
                    forges {
                      eid
                      name
                    }
                  }
                }
              }
            }""",
            **kwargs,
        )

        def get_data(r):
            orgs = r["data"]["currentUser"]["organizations"]
            return [item for org in orgs for item in org["welds"]]

        return _get_return(res, get_data=get_data)

    def get_weld(self, eid: Text, **kwargs):
        res = self.query(
            """
            query WeldQuery(
                #$organizationSlug: String!,
                #$slug: String!
                $eid: String!
            ) {
                weld(
                    #organizationSlug: $organizationSlug,
                    #slug: $slug
                    eid: $eid
                ) {
                    eid
                    slug
                    name
                    forges {
                        eid
                        name
                        slug
                    }
                }
            }""",
            variables=dict(eid=eid),
            **kwargs,
        )

        def get_data(r):
            return r["data"]["weld"]

        return _get_return(res, get_data=get_data)

    def create_etch_packet(
        self,
        payload: Optional[
            Union[
                dict,
                CreateEtchPacketPayload,
                CreateEtchPacket,
                AnyStr,
            ]
        ] = None,
        json=None,
        **kwargs,
    ):
        """Create etch packet via a graphql mutation."""
        # Create an etch packet payload instance excluding signers and files
        # (if any). We'll need to add those separately. below.
        if not any([payload, json]):
            raise TypeError('One of the arguments `payload` or `json` must exist')

        if json:
            payload = CreateEtchPacketPayload.parse_raw(
                json, content_type="application/json"
            )

        if isinstance(payload, dict):
            mutation = CreateEtchPacket.create_from_dict(payload)
        elif isinstance(payload, CreateEtchPacketPayload):
            mutation = CreateEtchPacket(payload=payload)
        elif isinstance(payload, CreateEtchPacket):
            mutation = payload
        else:
            raise ValueError(
                "`payload` must be a valid CreateEtchPacket instance or dict"
            )

        files = get_multipart_payload(mutation)

        res = self.mutate_multipart(files, **kwargs)
        return res

    def generate_etch_signing_url(self, signer_eid: str, client_user_id: str, **kwargs):
        """Generate a signing URL for a given user."""
        mutation = GenerateEtchSigningURL(
            signer_eid=signer_eid,
            client_user_id=client_user_id,
        )
        payload = mutation.create_payload()
        return self.mutate(mutation, variables=payload.dict(by_alias=True), **kwargs)

    def download_documents(self, document_group_eid: str, **kwargs):
        """Retrieve all completed documents in zip form."""
        api = PlainRequest(client=self.client)
        return api.get(f"document-group/{document_group_eid}.zip", **kwargs)

    def forge_submit(
        self,
        payload: Optional[Union[Dict[Text, Any], ForgeSubmitPayload]] = None,
        json=None,
        **kwargs,
    ):
        """Create a Webform (forge) submission via a graphql mutation."""
        if not any([json, payload]):
            raise TypeError('One of arguments `json` or `payload` are required')

        if json:
            payload = ForgeSubmitPayload.parse_raw(
                json, content_type="application/json"
            )

        if isinstance(payload, dict):
            mutation = ForgeSubmit.create_from_dict(payload)
        elif isinstance(payload, ForgeSubmitPayload):
            mutation = ForgeSubmit(payload=payload)
        else:
            raise ValueError(
                "`payload` must be a valid ForgeSubmitPayload instance or dict"
            )

        return self.mutate(
            mutation,
            variables=mutation.create_payload().dict(by_alias=True, exclude_none=True),
            **kwargs,
        )
